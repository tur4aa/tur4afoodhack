# Security Specification: tur4a FoodHack (Firestore Backend)

## 1. Data Invariants
1. **User Ownership (Boundary Lock)**: A user can only read and write their own data. Any document under `/users/{userId}/...` must strictly require `request.auth.uid == userId`.
2. **Identity Integrity**: No user can write data claiming to belong to another owner (`request.auth.uid` must match `{userId}`).
3. **No Unauthenticated Access**: Public/anonymous reads or writes are completely prohibited.
4. **Data Verification**: Email verification state is enforced if desired, or at standard authentication levels (`request.auth != null`).
5. **Type Constraints**: Meal types must be strictly lists, and each item in these collections must have valid, bounded numerical values (e.g. `kcal >= 0`, `protein >= 0`, `fat >= 0`, `carb >= 0`).

---

## 2. The "Dirty Dozen" Payloads (Exploit Vector Simulation)

### Payload 1: ID Poisoning Attack on Date Document
- **Target Path**: `/users/attackerUID/days/invalid_date_long_junk_string_with_excess_payload_sizes_xxxxxxxxxxxxxxxxxxxx`
- **Attempt**: Write a document with malicious path variables.
- **Expected Outcome**: `PERMISSION_DENIED` thanks to regex validation block `isValidDate(date)`.

### Payload 2: Cross-User Read/Write (Identity Spoofing)
- **Target Path**: `/users/victimUID/days/2026-06-01`
- **Attempt**: Attacker calls `setDoc` with authenticated token for `attackerUID`.
- **Expected Outcome**: `PERMISSION_DENIED` since `request.auth.uid != victimUID`.

### Payload 3: Unauthenticated Day Data Insertion
- **Target Path**: `/users/someUID/days/2026-06-01`
- **Attempt**: Unauthenticated client attempts to write a default day template.
- **Expected Outcome**: `PERMISSION_DENIED` since `request.auth == null`.

### Payload 4: Type Poisoning in Meal Array
- **Target Path**: `/users/userUID/days/2026-06-01`
- **Attempt**: User logs a breakfast containing a flat string `"hacked"` instead of a proper Map structure of food fields.
- **Expected Outcome**: `PERMISSION_DENIED` since list items must be strict Maps if present, with proper number fields.

### Payload 5: Negative Nutrition Value Injection
- **Target Path**: `/users/userUID/days/2026-06-01`
- **Attempt**: User sets breakfast item `kcal` value to `-99999` to cheat calorie calculations.
- **Expected Outcome**: `PERMISSION_DENIED` (all numeric inputs must be positive numbers).

### Payload 6: Overflow Calorie Attack (Denial of Compute)
- **Target Path**: `/users/userUID/days/2026-06-01`
- **Attempt**: User sets breakfast item `kcal` values to `999999999` (extremely large values) to overflow displays.
- **Expected Outcome**: `PERMISSION_DENIED` (kcal bounded, e.g., `<= 10000`).

### Payload 7: Injected String Fields in Template Number Inputs
- **Target Path**: `/users/userUID/templates/temp-abc`
- **Attempt**: Send `kcal` value as string `"121"` or `"NaN"` instead of double/integer.
- **Expected Outcome**: `PERMISSION_DENIED` due to exact type checking (`kcal is number`).

### Payload 8: Immutable Field Tampering (Timestamp Poisoning)
- **Target Path**: `/users/userUID/days/2026-06-01`
- **Attempt**: Update an historical day with a manipulated outdated `updatedAt` client-provided timestamp.
- **Expected Outcome**: `PERMISSION_DENIED` because update timestamps must match `request.time`.

### Payload 9: Shadow Field Write on Template Creation
- **Target Path**: `/users/userUID/templates/temp-abc`
- **Attempt**: Add a secret role property like `isAdmin: true` inside a user's local food template.
- **Expected Outcome**: `PERMISSION_DENIED` because schema enforces `keys().hasAll()` checks and strict length bounding.

### Payload 10: State Bypass/Relational Poisoning inside Day Data
- **Target Path**: `/users/userUID/days/2026-06-01`
- **Attempt**: Write `dayData` where the date key does not have the mandatory fields `breakfast`, `lunch`, `dinner`, and `snack`.
- **Expected Outcome**: `PERMISSION_DENIED` as all four meal arrays are required in schema validation.

### Payload 11: Too Large Array (Denial of Wallet)
- **Target Path**: `/users/userUID/days/2026-06-01`
- **Attempt**: Insert an array with 500 breakfast records to cause performance bloat.
- **Expected Outcome**: `PERMISSION_DENIED` since meals are size-capped.

### Payload 12: Injection Attack on Template Name
- **Target Path**: `/users/userUID/templates/temp-abc`
- **Attempt**: Send a 10MB malicious template name string.
- **Expected Outcome**: `PERMISSION_DENIED` since names have strict upper size boundaries (e.g., `<= 100` characters).

---

## 3. Test Runner (Firebase Rules Declarative Guard Assertion)
See the implementation of rules in `/firestore.rules` where guards map directly to preventing these payloads from execution.
