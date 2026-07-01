"""Local synthetic NBC-style banking app used to verify the Module 1 crawler for
real (login, transaction-number normalization, wizard pages, a popup, an iframe,
Shadow DOM, dropdowns/checkboxes/radios/date-picker, a mandatory field, a readonly
field, and a validation message) without needing a live NBC/UAT environment.

Run: python app.py  (serves on http://127.0.0.1:9100)
"""

import itertools

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn

app = FastAPI()

VALID_USER = "tester"
VALID_PASSWORD = "Passw0rd!"
APPROVER_USER = "approver"
APPROVER_PASSWORD = "Approve123!"
STORED_TRANSACTION_NUMBER = "001060"
STORED_TRANSACTION_NAME = "Cash Withdrawal"

_approval_id_counter = itertools.count(1)
PENDING_APPROVALS: dict[int, dict] = {}


def _normalize(raw: str) -> set[str]:
    stripped = raw.strip()
    if not stripped.isdigit():
        return {stripped.lower()}
    no_zeros = stripped.lstrip("0") or "0"
    return {stripped, no_zeros, no_zeros.zfill(4), no_zeros.zfill(6), no_zeros.zfill(8)}


def _page(body: str, title: str = "NBC Banking Test Generator") -> HTMLResponse:
    return HTMLResponse(
        f"""<!DOCTYPE html><html><head><title>{title}</title></head>
        <body style="font-family: Arial, sans-serif; margin: 40px;">{body}</body></html>"""
    )


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/login")


@app.get("/login", response_class=HTMLResponse)
def login_page():
    return _page(
        """
        <h2>NBC Banking Test Generator - Login</h2>
        <form method="post" action="/login">
          <label for="username">User ID</label><br/>
          <input type="text" id="username" name="username" placeholder="User ID" /><br/><br/>
          <label for="password">Password</label><br/>
          <input type="password" id="password" name="password" placeholder="Password" /><br/><br/>
          <button type="submit">Login</button>
        </form>
        """
    )


@app.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...)):
    if username == VALID_USER and password == VALID_PASSWORD:
        response = RedirectResponse("/search", status_code=303)
        response.set_cookie("nbc_session", "1")
        response.set_cookie("nbc_role", "maker")
        return response
    if username == APPROVER_USER and password == APPROVER_PASSWORD:
        response = RedirectResponse("/approvals", status_code=303)
        response.set_cookie("nbc_session", "1")
        response.set_cookie("nbc_role", "checker")
        return response
    return _page("<p>Invalid credentials.</p><a href='/login'>Back</a>")


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    if request.cookies.get("nbc_session") != "1":
        return RedirectResponse("/login")
    return _page(
        """
        <h2>Transaction Search</h2>
        <form method="post" action="/search">
          <label for="transaction">Transaction Number or Name</label><br/>
          <input type="text" id="transaction" name="transaction" placeholder="Transaction Number or Name" /><br/><br/>
          <button type="submit">Search</button>
        </form>
        """
    )


@app.post("/search")
def search_submit(transaction: str = Form(...)):
    candidates = _normalize(transaction)
    if (
        transaction.strip().lower() == STORED_TRANSACTION_NAME.lower()
        or candidates & _normalize(STORED_TRANSACTION_NUMBER)
    ):
        return RedirectResponse("/wizard/1", status_code=303)
    return _page(f"<p>No transaction found matching '{transaction}'.</p><a href='/search'>Back</a>")


@app.get("/wizard/1", response_class=HTMLResponse)
def wizard_1():
    return _page(
        """
        <a href="/logout" id="logoutLink" style="float:right;">Logout</a>
        <h2>Cash Withdrawal - Step 1 of 3</h2>
        <form>
          <label for="customer_name">Customer Name <span class="red-star" style="color:red">*</span></label><br/>
          <input type="text" id="customer_name" name="customer_name" required placeholder="Customer Name" /><br/><br/>

          <label for="account_number">Account Number <span class="red-star" style="color:red">*</span></label><br/>
          <input type="text" id="account_number" name="account_number" required placeholder="Account Number"
                 onblur="document.getElementById('charge_popup').style.display='block';" /><br/><br/>

          <div id="charge_popup" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.4); z-index:999;">
            <div style="background:white; max-width:320px; margin:100px auto; padding:16px; border:2px solid purple;">
              <strong>Alerts</strong>
              <p>Applicable charge on the account is Rs.: 0.00</p>
              <button type="button" id="charge_popup_ok"
                      onclick="document.getElementById('charge_popup').style.display='none';">OK</button>
            </div>
          </div>

          <label for="amount">Amount</label><br/>
          <input type="text" id="amount" name="amount" placeholder="Amount" /><br/><br/>

          <label for="currency">Currency</label><br/>
          <select id="currency" name="currency">
            <option value="USD">USD</option>
            <option value="EUR">EUR</option>
            <option value="INR">INR</option>
          </select><br/><br/>

          <iframe src="/wizard/1/iframe-panel" id="branch-frame" style="width:400px;height:120px;border:1px solid #ccc;"></iframe><br/><br/>

          <button type="button" onclick="window.open('/popup/customer-details','popup','width=420,height=320')">View Customer Details</button>
          <button type="button" id="view_summary_btn" onclick="
            var acct = document.getElementById('account_number').value;
            if (acct) { window.location.href = '/wizard/1/account-summary?acct=' + encodeURIComponent(acct); }
          ">View Account Summary</button>
          <button type="button" onclick="window.location.href='/wizard/2'">Next</button>
        </form>
        """
    )


@app.get("/wizard/1/account-summary", response_class=HTMLResponse)
def wizard_1_account_summary(acct: str = ""):
    return _page(
        f"""
        <h2>Account Summary</h2>
        <label for="account_status">Account Status</label><br/>
        <input type="text" id="account_status" name="account_status" readonly value="Active - {acct}" /><br/><br/>
        <a href="/wizard/1">Back</a>
        """,
        title="Account Summary",
    )


@app.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("nbc_session")
    response.delete_cookie("nbc_role")
    return response


@app.get("/wizard/1/iframe-panel", response_class=HTMLResponse)
def wizard_1_iframe_panel():
    return _page(
        """
        <label for="branch_code">Branch Code <span class="red-star" style="color:red">*</span></label><br/>
        <input type="text" id="branch_code" name="branch_code" required placeholder="Branch Code" />
        """
    )


@app.get("/popup/customer-details", response_class=HTMLResponse)
def popup_customer_details():
    return _page(
        """
        <h3>Customer Details</h3>
        <label for="customer_id">Customer ID</label><br/>
        <input type="text" id="customer_id" name="customer_id" readonly value="CUST-88421" /><br/><br/>
        <label for="customer_note">Relationship Manager Note</label><br/>
        <textarea id="customer_note" name="customer_note" placeholder="Note"></textarea>
        """,
        title="Customer Details",
    )


@app.get("/wizard/2", response_class=HTMLResponse)
def wizard_2():
    return _page(
        """
        <h2>Cash Withdrawal - Step 2 of 3</h2>
        <form>
          <label>
            <input type="checkbox" id="notify_customer" name="notify_customer" /> Notify customer
          </label><br/><br/>

          <label>Transfer Mode</label><br/>
          <input type="radio" id="mode_neft" name="transfer_mode" value="NEFT" /> <label for="mode_neft">NEFT</label>
          <input type="radio" id="mode_rtgs" name="transfer_mode" value="RTGS" /> <label for="mode_rtgs">RTGS</label>
          <input type="radio" id="mode_imps" name="transfer_mode" value="IMPS" /> <label for="mode_imps">IMPS</label>
          <br/><br/>

          <label for="value_date">Value Date <span class="red-star" style="color:red">*</span></label><br/>
          <input type="date" id="value_date" name="value_date" required /><br/><br/>

          <label for="reference_number">Reference Number</label><br/>
          <input type="text" id="reference_number" name="reference_number" readonly value="REF-2026-0617" /><br/><br/>

          <div class="field-error">Amount exceeds the single-transaction withdrawal limit of 50,000.</div><br/>

          <button type="button" onclick="window.location.href='/wizard/3'">Next</button>
        </form>
        """
    )


@app.get("/wizard/3", response_class=HTMLResponse)
def wizard_3():
    return _page(
        """
        <h2>Cash Withdrawal - Step 3 of 3 (Confirmation)</h2>
        <form method="post" action="/wizard/3/submit-for-approval">
          <nbc-remarks></nbc-remarks>

          <button type="submit">Submit for Approval</button>
        </form>
        <script>
          class NbcRemarks extends HTMLElement {
            connectedCallback() {
              const shadow = this.attachShadow({mode: 'open'});
              shadow.innerHTML = `
                <label for="remarks">Remarks</label><br/>
                <textarea id="remarks" name="remarks" placeholder="Additional remarks"></textarea>
              `;
            }
          }
          customElements.define('nbc-remarks', NbcRemarks);
        </script>
        """
    )


@app.post("/wizard/3/submit-for-approval")
def submit_for_approval():
    approval_id = next(_approval_id_counter)
    PENDING_APPROVALS[approval_id] = {
        "id": approval_id,
        "transaction_number": STORED_TRANSACTION_NUMBER,
        "transaction_name": STORED_TRANSACTION_NAME,
        "status": "pending_approval",
    }
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("nbc_session")
    response.delete_cookie("nbc_role")
    return response


@app.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request):
    if request.cookies.get("nbc_session") != "1" or request.cookies.get("nbc_role") != "checker":
        return RedirectResponse("/login")

    rows = "".join(
        f"""<tr>
              <td>{a['id']}</td><td>{a['transaction_number']}</td><td>{a['transaction_name']}</td><td class="approval-status">{a['status']}</td>
              <td><form method="post" action="/approvals/{a['id']}/approve" style="display:inline">
                    <button type="submit">Approve</button>
                  </form></td>
            </tr>"""
        for a in PENDING_APPROVALS.values()
        if a["status"] == "pending_approval"
    )
    return _page(
        f"""
        <h2>Pending Approvals</h2>
        <table border="1" cellpadding="6">
          <tr><th>ID</th><th>Transaction Number</th><th>Transaction Name</th><th>Status</th><th>Action</th></tr>
          {rows or '<tr><td colspan="5">No pending approvals</td></tr>'}
        </table>
        """,
        title="Pending Approvals",
    )


@app.post("/approvals/{approval_id}/approve")
def approve(approval_id: int):
    if approval_id in PENDING_APPROVALS:
        PENDING_APPROVALS[approval_id]["status"] = "approved"
    return RedirectResponse("/approvals", status_code=303)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9100)
