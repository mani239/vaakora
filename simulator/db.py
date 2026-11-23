import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(os.getenv("DB_PATH") or (Path(__file__).resolve().parent / "telecalling.db"))


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()

    # 1. Workspace / Business Account
    c.execute("""
    CREATE TABLE IF NOT EXISTS workspace (
        id TEXT PRIMARY KEY,
        business_name TEXT NOT NULL,
        website TEXT,
        industry TEXT,
        description TEXT,
        credits_balance REAL DEFAULT 50.00,
        currency TEXT DEFAULT 'INR',
        updated_at TEXT
    )
    """)

    # 2. SIM / Telephony Trunks
    c.execute("""
    CREATE TABLE IF NOT EXISTS sim_connections (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL, -- 'vobiz', 'sim_gateway', 'exotel', 'tatatele', 'twilio', 'plivo'
        phone_number TEXT NOT NULL,
        caller_name TEXT,
        status TEXT DEFAULT 'active', -- 'active', 'testing', 'disconnected'
        channels INTEGER DEFAULT 2,
        credentials JSON,
        created_at TEXT
    )
    """)

    # 3. AI Voice Employees (English-Only Cartesia Profiles)
    c.execute("""
    CREATE TABLE IF NOT EXISTS voice_employees (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'Outbound Sales Executive',
        voice_id TEXT NOT NULL DEFAULT 'aria',
        primary_lang TEXT NOT NULL DEFAULT 'en-IN',
        supported_langs TEXT DEFAULT 'en-IN',
        first_sentence TEXT,
        knowledge_base TEXT,
        custom_instructions TEXT,
        calling_hours_start TEXT DEFAULT '09:00',
        calling_hours_end TEXT DEFAULT '20:00',
        created_at TEXT
    )
    """)

    # 4. Leads Directory
    c.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id TEXT PRIMARY KEY,
        phone TEXT NOT NULL,
        name TEXT,
        company TEXT,
        industry TEXT,
        status TEXT DEFAULT 'new',
        custom_notes TEXT,
        created_at TEXT
    )
    """)

    # 5. Call Logs & Reports
    c.execute("""
    CREATE TABLE IF NOT EXISTS call_logs (
        id TEXT PRIMARY KEY,
        customer_phone TEXT NOT NULL,
        customer_name TEXT,
        employee_id TEXT,
        duration_seconds INTEGER DEFAULT 0,
        billed_credits REAL DEFAULT 0.00,
        status TEXT DEFAULT 'completed',
        qualification_status TEXT DEFAULT 'WARM',
        identified_need TEXT,
        decision_maker_role TEXT,
        agreed_next_step TEXT,
        summary TEXT,
        transcript JSON,
        created_at TEXT
    )
    """)

    # 6. Custom Cloned Voices (Cartesia Instant Voice Clone profiles, e.g. UK / Custom Accent)
    c.execute("""
    CREATE TABLE IF NOT EXISTS custom_voices (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cartesia_id TEXT NOT NULL,
        accent TEXT DEFAULT 'en-GB',
        gender TEXT DEFAULT 'female',
        description TEXT,
        created_at TEXT
    )
    """)

    # 7. Public Contact & Demo Inquiries (from Trust / Contact form)
    c.execute("""
    CREATE TABLE IF NOT EXISTS contact_inquiries (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        phone TEXT,
        company TEXT,
        leads_per_day TEXT,
        message TEXT,
        created_at TEXT
    )
    """)

    c.execute("PRAGMA table_info(workspace)")
    existing_ws_cols = {row[1] for row in c.fetchall()}
    if "pitch_hook" not in existing_ws_cols:
        c.execute(
            "ALTER TABLE workspace ADD COLUMN pitch_hook TEXT DEFAULT "
            "'Hi there, this is Aria calling from Pontis LLP in Hyderabad. We help businesses with AI dubbing and video localization. Do you have 30 seconds?'"
        )
    if "target_audience" not in existing_ws_cols:
        c.execute("ALTER TABLE workspace ADD COLUMN target_audience TEXT DEFAULT 'Microdrama Studios, OTT Producers, EdTech Companies'")
    if "operating_hours" not in existing_ws_cols:
        c.execute("ALTER TABLE workspace ADD COLUMN operating_hours TEXT DEFAULT '09:30 - 19:30'")

    c.execute("PRAGMA table_info(sim_connections)")
    existing_sim_cols = {row[1] for row in c.fetchall()}
    if "carrier" not in existing_sim_cols:
        c.execute("ALTER TABLE sim_connections ADD COLUMN carrier TEXT DEFAULT 'Jio 5G / Airtel'")
    if "sim_slot" not in existing_sim_cols:
        c.execute("ALTER TABLE sim_connections ADD COLUMN sim_slot INTEGER DEFAULT 1")

    # Seed default workspace if empty
    c.execute("SELECT COUNT(*) FROM workspace")
    if c.fetchone()[0] == 0:
        c.execute("""
        INSERT INTO workspace (id, business_name, website, industry, description, credits_balance, updated_at)
        VALUES ('ws_default', 'Pontis LLP', 'https://pontis.in', 'Multimedia & AI Localization',
                'Language localization, AI dubbing, voice-over, and microdrama production across 180+ languages.', 50.00, datetime('now'))
        """)

    # Migrate untouched Telugu stock workspace/employee defaults to English-only
    c.execute("""
        UPDATE workspace
        SET pitch_hook = 'Hi there, this is Aria calling from Pontis LLP in Hyderabad. We help studios and businesses with AI dubbing and video localization. Do you have 30 seconds?'
        WHERE id = 'ws_default' AND (pitch_hook IS NULL OR pitch_hook LIKE '%నమస్కారం%')
    """)

    # Seed default SIM/SIP trunk if empty
    c.execute("SELECT COUNT(*) FROM sim_connections")
    if c.fetchone()[0] == 0:
        c.execute("""
        INSERT INTO sim_connections (id, provider, phone_number, caller_name, status, channels, created_at)
        VALUES ('sim_01', 'vobiz', '+91 80 4736 9102', 'Pontis Vobiz SIP Trunk', 'active', 4, datetime('now'))
        """)

    # Seed default English voice employee if empty
    c.execute("SELECT COUNT(*) FROM voice_employees")
    if c.fetchone()[0] == 0:
        c.execute("""
        INSERT INTO voice_employees (id, name, role, voice_id, primary_lang, supported_langs, first_sentence, knowledge_base, custom_instructions, created_at)
        VALUES ('emp_01', 'Aria', 'Outbound Sales Executive', 'aria', 'en-IN', 'en-IN',
                'Hi there, this is Aria, an AI assistant calling from Pontis LLP in Hyderabad. We help studios and businesses with AI dubbing and video localization. Do you have 30 seconds?',
                'Pontis LLP specializes in multilingual localization across 180+ languages. Services include AI dubbing, lip-sync, microdrama video production, and SCORM e-learning courseware.',
                'Speak natural conversational Indian English. Acknowledge what the prospect said before answering. Offer WhatsApp sample reels only once when relevant. Never invent prices.',
                datetime('now'))
        """)
    else:
        c.execute("""
            UPDATE voice_employees
            SET name = 'Aria',
                voice_id = 'aria',
                primary_lang = 'en-IN',
                supported_langs = 'en-IN',
                first_sentence = 'Hi there, this is Aria, an AI assistant calling from Pontis LLP in Hyderabad. We help studios and businesses with AI dubbing and video localization. Do you have 30 seconds?',
                custom_instructions = 'Speak natural conversational Indian English. Acknowledge what the prospect said before answering. Offer WhatsApp sample reels only once when relevant. Never invent prices.'
            WHERE id = 'emp_01'
              AND (
                voice_id = 'kavitha'
                OR primary_lang = 'te-IN'
                OR first_sentence = 'Hi there, this is Aria calling from Pontis LLP in Hyderabad. We help studios and businesses with AI dubbing and video localization. Do you have 30 seconds?'
              )
        """)

    # Seed sample leads if empty
    c.execute("SELECT COUNT(*) FROM leads")
    if c.fetchone()[0] == 0:
        c.executemany("""
        INSERT INTO leads (id, phone, name, company, industry, status, custom_notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """, [
            ('lead_01', '+91 98490 12345', 'Suresh Varma', 'Vyjayanthi Microdramas', 'Microdrama / OTT', 'qualified_hot', 'Produces 3 short series monthly in Hyderabad. Wants regional-to-English & pan-India dubbing.'),
            ('lead_02', '+91 97001 98765', 'Ananya Rao', 'SkillSpire EdTech', 'E-Learning / EdTech', 'new', 'Looking for SCORM courseware localization for corporate training.'),
            ('lead_03', '+91 91234 56789', 'Kiran Kumar', 'Apex Media Works', 'Ad Agency', 'new', 'Digital campaign dubbing into global and Indian languages.')
        ])

    conn.commit()
    conn.close()


def get_employee(employee_id: str = "emp_01", *, fallback_first: bool = True) -> dict | None:
    """Fetch a voice employee row by ID, optionally falling back to the first profile."""
    conn = get_connection()
    try:
        target_id = (employee_id or "emp_01").strip()
        row = conn.execute("SELECT * FROM voice_employees WHERE id = ?", (target_id,)).fetchone()
        if not row and fallback_first:
            row = conn.execute("SELECT * FROM voice_employees ORDER BY created_at ASC LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_lead(lead_id: str) -> dict | None:
    """Fetch a lead row by ID, returning None if not found."""
    clean_id = (lead_id or "").strip()
    if not clean_id:
        return None
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (clean_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def record_completed_call(
    *,
    call_id: str,
    customer_phone: str,
    customer_name: str,
    employee_id: str,
    duration_seconds: int,
    billed_credits: float,
    qualification_status: str,
    identified_need: str,
    decision_maker_role: str,
    agreed_next_step: str,
    summary: str,
    transcript: list[dict],
    lead_id: str = "",
) -> str:
    """Persist a completed call log, deduct workspace credits, and update lead qualification status."""
    q_upper = (qualification_status or "WARM").strip().upper()
    lead_status = "qualified_hot" if q_upper == "HOT" else ("qualified_warm" if q_upper == "WARM" else "called")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO call_logs (
                id, customer_phone, customer_name, employee_id, duration_seconds,
                billed_credits, status, qualification_status, identified_need,
                decision_maker_role, agreed_next_step, summary, transcript, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                call_id,
                customer_phone,
                customer_name,
                employee_id or "emp_01",
                int(duration_seconds),
                float(billed_credits),
                q_upper,
                identified_need or "",
                decision_maker_role or "",
                agreed_next_step or "",
                summary or "",
                json.dumps(transcript or []),
            ),
        )
        conn.execute(
            "UPDATE workspace SET credits_balance = MAX(0.0, credits_balance - ?) WHERE id = 'ws_default'",
            (float(billed_credits),),
        )
        if lead_id:
            conn.execute("UPDATE leads SET status = ? WHERE id = ?", (lead_status, lead_id))
        conn.commit()
    finally:
        conn.close()
    return lead_status


def list_custom_voices() -> list[dict]:
    """Return all custom cloned voices stored in SQLite."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_voices'"
        ).fetchall()
        if not rows:
            return []
        vrows = conn.execute("SELECT * FROM custom_voices ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in vrows]
    finally:
        conn.close()


def get_custom_voice(voice_key: str) -> dict | None:
    """Look up a custom cloned voice by its key or Cartesia UUID."""
    clean = (voice_key or "").strip()
    if not clean:
        return None
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_voices'"
        ).fetchall()
        if not rows:
            return None
        row = conn.execute(
            "SELECT * FROM custom_voices WHERE lower(id) = lower(?) OR lower(cartesia_id) = lower(?)",
            (clean, clean),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_custom_voice(
    *,
    voice_key: str,
    name: str,
    cartesia_id: str,
    accent: str = "en-GB",
    gender: str = "female",
    description: str = "",
) -> dict:
    """Save or update a Cartesia cloned voice in SQLite."""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_voices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cartesia_id TEXT NOT NULL,
                accent TEXT DEFAULT 'en-GB',
                gender TEXT DEFAULT 'female',
                description TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO custom_voices (id, name, cartesia_id, accent, gender, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                voice_key.strip().lower(),
                name.strip(),
                cartesia_id.strip(),
                (accent or "en-GB").strip(),
                (gender or "female").strip().lower(),
                (description or f"Cloned {accent or 'en-GB'} voice via Cartesia Sonic").strip(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_custom_voice(voice_key) or {
        "id": voice_key.strip().lower(),
        "name": name.strip(),
        "cartesia_id": cartesia_id.strip(),
        "accent": accent,
        "gender": gender,
        "description": description,
    }


def create_contact_inquiry(
    *,
    inquiry_id: str,
    name: str,
    email: str,
    phone: str = "",
    company: str = "",
    leads_per_day: str = "",
    message: str = "",
) -> dict:
    """Persist a contact or demo inquiry submitted via the public /trust or contact form."""
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contact_inquiries (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT,
                company TEXT,
                leads_per_day TEXT,
                message TEXT,
                created_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO contact_inquiries (id, name, email, phone, company, leads_per_day, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                inquiry_id.strip(),
                name.strip(),
                email.strip(),
                (phone or "").strip(),
                (company or "").strip(),
                (leads_per_day or "").strip(),
                (message or "").strip(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM contact_inquiries WHERE id = ?", (inquiry_id.strip(),)).fetchone()
        return dict(row) if row else {"id": inquiry_id, "name": name, "email": email}
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)
