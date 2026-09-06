from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body_data = self.rfile.read(content_length).decode('utf-8')
        try:
            req = json.loads(body_data)
        except Exception:
            self._send_json({'error': 'Invalid JSON'}, status=400)
            return

        token = req.get('token')
        org_id = req.get('org_id')
        api_domain = req.get('api_domain', 'https://www.zohoapis.com')
        name = req.get('name', 'Client')
        email = req.get('email')
        amount = float(req.get('amount', 1500))
        product = req.get('product', 'Professional Services')
        custom_subject = req.get('subject')
        custom_body = req.get('body')
        payment_link = req.get('payment_link', 'https://books.zoho.com')

        if not token or not org_id or not email:
            self._send_json({'error': 'Missing required fields (token, org_id, email)'}, status=400)
            return

        headers = {
            'Authorization': f'Zoho-oauthtoken {token}',
            'Content-Type': 'application/json;charset=UTF-8'
        }

        try:
            # 1. Find or Create Contact in Zoho Books
            cust_id = self._get_or_create_contact(api_domain, org_id, headers, name, email)

            # 2. Create Invoice in Zoho Books
            inv_data = self._create_invoice(api_domain, org_id, headers, cust_id, product, amount)
            inv_id = str(inv_data['invoice_id'])
            inv_num = inv_data.get('invoice_number', f'INV-{inv_id}')

            # 3. Format Subject
            formatted_amount = f"${amount:,.2f}"
            subject = custom_subject or f"Invoice #{inv_num} for {name} ({formatted_amount})"
            subject = subject.replace('{{invoice_number}}', inv_num).replace('{{client_name}}', name).replace('{{amount}}', formatted_amount).replace('{{product}}', product)

            # User custom body text (or clean default)
            user_msg = custom_body or f"Hello {name},\n\nPlease find attached your official invoice #{inv_num} for {product} ({formatted_amount}).\n\nThank you for your business!"
            user_msg = user_msg.replace('{{invoice_number}}', inv_num).replace('{{client_name}}', name).replace('{{amount}}', formatted_amount).replace('{{product}}', product)

            # Convert plain linebreaks to clean styled paragraphs
            msg_html = "".join([f"<p style=\"margin:0 0 12px 0; font-size:14px; line-height:1.6; color:#334155;\">{l}</p>" for l in user_msg.split('\n') if l.strip()])

            # Tracking beacon
            host = self.headers.get('Host', 'zoho-invoicepulse.vercel.app')
            beacon_url = f"https://{host}/api/track?id={inv_num}&email={urllib.parse.quote(email)}"

            # 4. Strict Inline HTML Email Template with Beautiful CTA Button
            styled_html = f"""<table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color:#f1f5f9; padding:24px 0; font-family:Arial, sans-serif;">
  <tr>
    <td align="center">
      <table width="560" border="0" cellspacing="0" cellpadding="0" style="max-width:560px; width:100%; background-color:#ffffff; border-radius:10px; border:1px solid #e2e8f0; overflow:hidden; box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);">
        <!-- Card Header -->
        <tr>
          <td style="background-color:#1e40af; padding:22px 28px; text-align:left;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0">
              <tr>
                <td style="font-size:20px; font-weight:bold; color:#ffffff; letter-spacing:-0.02em;">My Store</td>
                <td align="right" style="font-size:13px; color:#bfdbfe; font-family:monospace; font-weight:bold;">#{inv_num}</td>
              </tr>
            </table>
          </td>
        </tr>
        <!-- Card Body -->
        <tr>
          <td style="padding:28px 28px 20px 28px;">
            {msg_html}

            <!-- Invoice Item & Total Box -->
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin:20px 0; background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;">
              <tr>
                <td style="padding:16px 20px;">
                  <table width="100%" border="0" cellspacing="0" cellpadding="0">
                    <tr>
                      <td style="font-size:13px; color:#64748b;"><strong>Item / Service:</strong></td>
                      <td align="right" style="font-size:13px; color:#0f172a; font-weight:600;">{product}</td>
                    </tr>
                    <tr>
                      <td style="font-size:13px; color:#64748b; padding-top:8px;"><strong>Total Amount Due:</strong></td>
                      <td align="right" style="font-size:18px; color:#1e40af; font-weight:bold; padding-top:8px;">{formatted_amount}</td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>

            <!-- Styled CTA Button -->
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin:22px 0 16px 0;">
              <tr>
                <td align="center">
                  <a href="{payment_link}" target="_blank" style="display:inline-block; background-color:#2563eb; color:#ffffff; font-size:14px; font-weight:bold; text-decoration:none; padding:12px 28px; border-radius:6px; box-shadow:0 2px 4px rgba(37,99,235,0.3);">
                    💳 View &amp; Pay Invoice Online &rarr;
                  </a>
                </td>
              </tr>
            </table>

            <p style="margin:16px 0 0 0; font-size:12px; color:#64748b; text-align:center;">📎 The official PDF invoice copy is attached to this email.</p>
          </td>
        </tr>
        <!-- Card Footer -->
        <tr>
          <td style="background-color:#f8fafc; padding:14px 28px; border-top:1px solid #e2e8f0; font-size:11px; color:#94a3b8; text-align:center;">
            Sent securely via Zoho Books Invoice Engine &bull; Invoice Ref: {inv_num}
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
<img src="{beacon_url}" width="1" height="1" alt="" style="display:none!important;" />"""

            send_payload = {
                'send_attachment': True,
                'to_mail_ids': [email],
                'subject': subject,
                'body': styled_html
            }

            send_url = f"{api_domain}/books/v3/invoices/{inv_id}/email?organization_id={org_id}"
            req_send = urllib.request.Request(send_url, data=json.dumps(send_payload).encode('utf-8'), headers=headers, method='POST')

            with urllib.request.urlopen(req_send) as send_resp:
                resp_data = json.loads(send_resp.read().decode('utf-8'))
                self._send_json({'status': 'sent', 'invoiceNumber': inv_num, 'invoiceId': inv_id, 'zohoResponse': resp_data})

        except urllib.error.HTTPError as e:
            err_text = e.read().decode('utf-8')
            self._send_json({'error': f"Zoho API Error ({e.code}): {err_text}"}, status=e.code)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    def _get_or_create_contact(self, api_domain, org_id, headers, name, email):
        search_url = f"{api_domain}/books/v3/contacts?organization_id={org_id}&email={urllib.parse.quote(email)}"
        req_search = urllib.request.Request(search_url, headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req_search) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                contacts = data.get('contacts', [])
                if contacts:
                    return str(contacts[0]['contact_id'])
        except Exception:
            pass

        create_url = f"{api_domain}/books/v3/contacts?organization_id={org_id}"
        payload = {
            'contact_name': name or email.split('@')[0],
            'contact_persons': [{'first_name': name, 'email': email, 'is_primary_contact': True}]
        }
        req_create = urllib.request.Request(create_url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req_create) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return str(data['contact']['contact_id'])

    def _create_invoice(self, api_domain, org_id, headers, customer_id, product, amount):
        url = f"{api_domain}/books/v3/invoices?organization_id={org_id}"
        payload = {
            'customer_id': customer_id,
            'line_items': [{'name': product, 'rate': amount, 'quantity': 1}]
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['invoice']

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
