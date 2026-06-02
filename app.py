import json
import os
import secrets
from flask import Flask, request, jsonify, render_template, session
from database import get_connection, init_db, log_activity
from ai_engine import analyze_ticket, get_team, chatbot_response, smart_support_response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# On Render, set DATA_DIR=/data (persistent disk). Locally defaults to project root.
DATA_DIR   = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# ---------------------------------------------------------------------------
# Default accounts seeded into users.json if it is missing or empty.
# Change these credentials before deploying.
# ---------------------------------------------------------------------------
DEFAULT_USERS = [
    {
        "employee_id": "EMP001",
        "password": generate_password_hash("admin123"),
        "role": "admin",
    },
    {
        "employee_id": "EMP002",
        "password": generate_password_hash("user123"),
        "role": "user",
    },
]


# ---------------------------------------------------------------------------
# User persistence helpers
# ---------------------------------------------------------------------------

def load_users() -> list:
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_users(users: list) -> None:
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)


def seed_default_users() -> None:
    """Write DEFAULT_USERS to users.json only if the file is empty / missing."""
    users = load_users()
    if not users:
        save_users(DEFAULT_USERS)
        print("Default users seeded into users.json")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def current_user() -> dict | None:
    """Return the logged-in user dict, or None."""
    employee_id = session.get("employee_id")
    if not employee_id:
        return None
    users = load_users()
    return next((u for u in users if u["employee_id"] == employee_id), None)


def require_login():
    """Return a 401 response if no user is logged in, else None."""
    if not current_user():
        return jsonify({"message": "Unauthorized. Please log in."}), 401
    return None


def require_admin():
    """Return a 403 response if the logged-in user is not an admin, else None."""
    user = current_user()
    if not user:
        return jsonify({"message": "Unauthorized. Please log in."}), 401
    if user.get("role") != "admin":
        return jsonify({"message": "Forbidden. Admin access required."}), 403
    return None


# ---------------------------------------------------------------------------
# Initialise DB and seed users
# ---------------------------------------------------------------------------

init_db()
seed_default_users()


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    employee_id = (data.get("employee_id") or "").strip()
    password = (data.get("password") or "").strip()

    if not employee_id or not password:
        return jsonify({"message": "Employee ID and password are required."}), 400

    users = load_users()
    if any(u["employee_id"] == employee_id for u in users):
        return jsonify({"message": "Employee ID already exists."}), 400

    # Role is always "user" on public signup — clients cannot self-promote
    users.append({
        "employee_id": employee_id,
        "password": generate_password_hash(password),
        "role": "user",
    })
    save_users(users)
    return jsonify({"message": "Signup successful. You can now log in."})


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    employee_id = (data.get("employee_id") or "").strip()
    password = (data.get("password") or "").strip()

    if not employee_id or not password:
        return jsonify({"message": "Employee ID and password are required."}), 400

    users = load_users()
    user = next((u for u in users if u["employee_id"] == employee_id), None)

    if not user:
        return jsonify({"message": "Employee not found."}), 404

    if not check_password_hash(user["password"], password):
        return jsonify({"message": "Wrong password."}), 401

    # Store identity in server-side session
    session["employee_id"] = employee_id
    return jsonify({
        "message": "Login successful.",
        "role": user["role"],
        "employee_id": employee_id,
    })


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"message": "Logged out."})


@app.route('/me', methods=['GET'])
def me():
    """Return the current session user (used by the frontend on page load)."""
    user = current_user()
    if not user:
        return jsonify({"message": "Not logged in."}), 401
    return jsonify({
        "employee_id": user["employee_id"],
        "role": user["role"],
    })


# ---------------------------------------------------------------------------
# Ticket routes
# ---------------------------------------------------------------------------

@app.route('/tickets', methods=['POST'])
def submit_ticket():
    err = require_login()
    if err:
        return err

    data = request.get_json()
    user = current_user()

    # Always use the session identity as the ticket author
    name = user["employee_id"]
    department = data.get('department')
    title = (data.get('title') or "").strip()
    description = (data.get('description') or "").strip()

    if not all([department, title, description]):
        return jsonify({"error": "Department, title, and description are required."}), 400

    # Priority comes from the user's form selection
    priority = data.get("priority", "Medium")
    allowed_priorities = ["Low", "Medium", "High", "Critical"]
    if priority not in allowed_priorities:
        priority = "Medium"

    # AI analysis (summary + category only)
    ai_result = analyze_ticket(title, description)
    summary = ai_result.get('summary', 'No summary available.')
    category = ai_result.get('category', 'General')
    assigned_team = get_team(department)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tickets
            (name, department, title, description, category, priority,
             ai_summary, assigned_team)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (name, department, title, description, category, priority,
          summary, assigned_team))
    conn.commit()
    new_id = cursor.lastrowid

    reply_message = (
        f"Hello {name},\n\n"
        f"Your ticket #{new_id} has been created successfully.\n\n"
        f"Assigned Team: {assigned_team}\n"
        f"Priority: {priority}\n\n"
        f"Regards,\nSmartDesk AI"
    )
    log_activity(new_id, reply_message)
    log_activity(new_id, "Ticket Created")
    if priority == "Critical":
        log_activity(new_id, "Escalated to Senior Support")

    conn.close()
    return jsonify({
        "message": "Ticket submitted successfully.",
        "ticket_id": new_id,
        "ai_summary": summary,
        "category": category,
        "priority": priority,
    }), 201


@app.route('/tickets', methods=['GET'])
def get_tickets():
    err = require_login()
    if err:
        return err

    user = current_user()
    conn = get_connection()
    cursor = conn.cursor()

    if user["role"] == "admin":
        # Admins see all tickets
        cursor.execute('SELECT * FROM tickets ORDER BY created_at DESC')
    else:
        # Regular users see only their own tickets
        cursor.execute(
            'SELECT * FROM tickets WHERE name = ? ORDER BY created_at DESC',
            (user["employee_id"],)
        )

    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


@app.route('/tickets/<int:ticket_id>', methods=['PATCH'])
def update_ticket(ticket_id):
    # Only admins may change ticket status
    err = require_admin()
    if err:
        return err

    data = request.get_json()
    status = data.get('status')
    allowed = ['Open', 'In progress', 'Resolved', 'Closed']
    if status not in allowed:
        return jsonify({"error": "Invalid status."}), 400

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE tickets SET status = ? WHERE id = ?',
        (status, ticket_id)
    )
    conn.commit()
    log_activity(ticket_id, f"Status changed to {status}")
    conn.close()
    return jsonify({
        "message": "Status updated.",
        "ticket_id": ticket_id,
        "status": status,
    })


# ---------------------------------------------------------------------------
# Chatbot
# ---------------------------------------------------------------------------

@app.route('/chat', methods=['POST'])
def chat():
    err = require_login()
    if err:
        return err

    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({"reply": "Please enter a message."}), 400

    user = current_user()
    conn = get_connection()
    cursor = conn.cursor()

    if user["role"] == "admin":
        cursor.execute('SELECT * FROM tickets')
    else:
        cursor.execute(
            'SELECT * FROM tickets WHERE name = ?',
            (user["employee_id"],)
        )

    tickets = [dict(row) for row in cursor.fetchall()]
    conn.close()

    reply = chatbot_response(user_message, tickets)
    return jsonify({"reply": reply})


@app.route('/support-chat', methods=['POST'])
def support_chat():
    """
    Smart support chat endpoint.
    Accepts conversation history and the latest message.
    Returns AI reply + metadata (resolved, should_raise_ticket, ticket suggestions).
    If should_raise_ticket is true, automatically creates the ticket and returns its ID.
    """
    err = require_login()
    if err:
        return err

    data = request.get_json()
    user_message      = (data.get('message') or '').strip()
    conversation      = data.get('conversation', [])   # list of {role, content}
    force_ticket      = data.get('force_ticket', False)

    if not user_message:
        return jsonify({"error": "Message is required."}), 400

    user = current_user()

    # Get AI response
    result = smart_support_response(conversation, user_message)

    ticket_id      = None
    ticket_created = False

    # Auto-raise ticket if AI decides it's needed OR user explicitly forces it
    if result.get('should_raise_ticket') or force_ticket:
        title       = result.get('suggested_title', user_message[:80])
        department  = result.get('suggested_department', 'IT')
        priority    = result.get('suggested_priority', 'Medium')

        # Build a description from conversation history
        description_parts = [f"{m['role'].upper()}: {m['content']}" for m in conversation]
        description_parts.append(f"USER: {user_message}")
        description = "\n".join(description_parts)

        ai_result     = analyze_ticket(title, description)
        summary       = ai_result.get('summary', '')
        category      = ai_result.get('category', 'General')
        assigned_team = get_team(department)

        conn   = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tickets
                (name, department, title, description, category, priority,
                 ai_summary, assigned_team)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user["employee_id"], department, title, description,
            category, priority, summary, assigned_team
        ))
        conn.commit()
        ticket_id = cursor.lastrowid
        log_activity(ticket_id, "Ticket created via AI Support Chat")
        log_activity(ticket_id, f"Status changed to Open")
        if priority == "Critical":
            log_activity(ticket_id, "Escalated to Senior Support")
        conn.close()
        ticket_created = True

    return jsonify({
        "reply":             result.get('reply', ''),
        "resolved":          result.get('resolved', False),
        "should_raise_ticket": result.get('should_raise_ticket', False),
        "suggested_title":   result.get('suggested_title', ''),
        "suggested_department": result.get('suggested_department', 'IT'),
        "suggested_priority": result.get('suggested_priority', 'Medium'),
        "ticket_created":    ticket_created,
        "ticket_id":         ticket_id,
    })


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

@app.route('/activity/<int:ticket_id>', methods=['GET'])
def get_activity(ticket_id):
    err = require_login()
    if err:
        return err

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM activity_log WHERE ticket_id = ? ORDER BY id DESC',
        (ticket_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.route('/')
def home():
    return render_template('index.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=os.getenv('FLASK_DEBUG','0')=='1')