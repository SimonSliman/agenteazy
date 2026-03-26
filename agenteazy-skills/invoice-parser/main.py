from agenteazy_runtime import call_skill


def _safe_call(skill, data):
    try:
        result = call_skill(skill, data)
        if not isinstance(result, dict):
            return {"raw": str(result)}
        return result
    except Exception as e:
        return {"error": str(e)}


def parse(csv_text):
    """Parse invoice data from CSV. Returns structured invoices with dates, amounts, and validation."""
    try:
        # 1. Parse CSV into rows
        parsed = _safe_call("csv-parse", {"csv_text": csv_text})
        if parsed.get("error"):
            return parsed

        rows = parsed.get("rows", [])
        if not rows:
            return {"error": "No rows found in CSV"}

        invoices = []
        total_amount = 0

        for row in rows:
            invoice = {"original": row}

            # 2. Format currency if amount present
            amount_str = row.get("amount", row.get("total", row.get("price", "")))
            if amount_str:
                try:
                    amount = float(str(amount_str).replace("$", "").replace(",", "").strip())
                    invoice["amount"] = amount
                    total_amount += amount
                    formatted = _safe_call("currency-format", {"amount": amount, "currency": "USD"})
                    invoice["formatted_amount"] = formatted.get("formatted", str(amount))
                except ValueError:
                    invoice["amount_error"] = f"Could not parse: {amount_str}"

            # 3. Parse date if present
            date_str = row.get("date", row.get("invoice_date", row.get("due_date", "")))
            if date_str:
                invoice["date_raw"] = date_str

            # 4. Validate email if present
            email = row.get("email", row.get("contact", ""))
            if email and "@" in email:
                invoice["email_check"] = _safe_call("disposable-email-check", {"email": email})

            # 5. PII scrub notes/description
            notes = row.get("notes", row.get("description", row.get("memo", "")))
            if notes:
                invoice["pii_check"] = _safe_call("pii-scrub", {"text": notes})

            invoices.append(invoice)

        return {
            "invoice_count": len(invoices),
            "total_amount": round(total_amount, 2),
            "invoices": invoices,
        }
    except Exception as e:
        return {"error": str(e)}
