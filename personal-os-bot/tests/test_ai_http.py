"""The real AIClient against a local fake OpenAI-compatible server (no internet)."""
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from bot.ai import AIClient, AIConfig, AIError
from bot.nlp import CATEGORIES

CTX = {"now": datetime(2026, 10, 12, 14, 0), "tz": "Asia/Dubai", "currency": "AED", "categories": CATEGORIES}


class Server:
    def __init__(self, responses):
        self.responses = list(responses)   # (status, body_dict_or_str)
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                status, payload = outer.responses.pop(0)
                data = payload if isinstance(payload, str) else json.dumps(payload)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data.encode())

            def log_message(self, *a):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"

    def close(self):
        self.httpd.shutdown()


def ok(content):
    return 200, {"choices": [{"message": {"role": "assistant", "content": content}}]}


@pytest.fixture
def server():
    servers = []

    def make(*responses):
        s = Server(responses)
        servers.append(s)
        return s
    yield make
    for s in servers:
        s.close()


def client(url, vision="v"):
    return AIClient(AIConfig("test", "secret", url, "text-model", vision, timeout=5))


def test_text_request_shape(server):
    s = server(ok('{"items": [{"type": "expense", "amount": 18, "description": "кофе"}]}'))
    data = client(s.url).parse_text("кофе 18", CTX)
    assert data["items"][0]["amount"] == 18
    req = s.requests[0]
    assert req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer secret"
    body = req["body"]
    assert body["model"] == "text-model" and body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system" and "2026-10-12" in body["messages"][0]["content"]
    assert body["messages"][1] == {"role": "user", "content": "кофе 18"}


def test_image_request_uses_vision_model(server):
    s = server(ok('{"items": []}'))
    client(s.url).parse_image(b"\xff\xd8abc", "чек", CTX)
    body = s.requests[0]["body"]
    assert body["model"] == "v"
    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "чек"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_no_vision_model_refuses_images():
    with pytest.raises(AIError):
        client("http://127.0.0.1:9", vision="").parse_image(b"x", "", CTX)


def test_retry_without_json_mode_on_400(server):
    s = server((400, {"error": {"message": "response_format not supported"}}), ok('{"items": []}'))
    assert client(s.url).parse_text("x", CTX) == {"items": []}
    assert "response_format" not in s.requests[1]["body"]


@pytest.mark.parametrize("status,needle", [(429, "лимит"), (401, "ключ"), (404, "AI_MODEL")])
def test_http_errors_are_readable(server, status, needle):
    s = server((status, {"error": "x"}))
    with pytest.raises(AIError) as e:
        client(s.url).parse_text("x", CTX)
    assert needle in str(e.value)


def test_connection_refused():
    with pytest.raises(AIError):
        client("http://127.0.0.1:9/v1").parse_text("x", CTX)


def test_garbage_answer(server):
    s = server(ok("Извините, я не могу"))
    with pytest.raises(AIError):
        client(s.url).parse_text("x", CTX)
