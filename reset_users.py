import json
from werkzeug.security import generate_password_hash

users = [
    {
        "employee_id": "EMP001",
        "password": generate_password_hash("admin123"),
        "role": "admin"
    },
    {
        "employee_id": "EMP002",
        "password": generate_password_hash("user123"),
        "role": "user"
    }
]

with open("users.json", "w") as f:
    json.dump(users, f, indent=4)

print("users.json reset successfully!")
print("EMP001 / admin123 -> admin")
print("EMP002 / user123  -> user")