from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import re

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

        name = req.get('name', 'Client')
        email = req.get('email')
        amount = float(req.get('amount', 1500))
        product = req.get('product', 'Professional Services')
        custom_subject = req.get('subject')
        custom_body = req.get('body')

        token = req.get('token')
        org_id = req.get('org_id')
        api_domain = req.get('api_domain', 'https://www.zohoapis.com')

        if not email:
            self._send_json({'error': 'Missing required recipient email'}, status=400)
            return

        if not token or not org_id:
            self._send_json({'error': 'Missing required Zoho credentials (token, org_id)'}, status=400)
            return

        headers = {
            'Authorization': f'Zoho-oauthtoken {token}',
            'Content-Type': 'application/json;charset=UTF-8'
        }

        try:
            # 1. Find or Create Contact in Zoho Books/Invoice
            cust_id = self._get_or_create_contact(api_domain, org_id, headers, name, email)

            # 2. Create Invoice in Zoho Books/Invoice
            inv_data = self._create_invoice(api_domain, org_id, headers, cust_id, product, amount)
            inv_id = str(inv_data['invoice_id'])
            inv_num = inv_data.get('invoice_number', f'INV-{inv_id}')

            # 3. Format Subject & Hydrate User's Exact Custom Body
            formatted_amount = f"${amount:,.2f}"
            subject = custom_subject or f"Invoice #{inv_num} for {name} ({formatted_amount})"
            subject = subject.replace('{{invoice_number}}', inv_num).replace('{{client_name}}', name).replace('{{amount}}', formatted_amount).replace('{{product}}', product)

            # Clean raw HTML: collapse newline gaps that cause email clients to inject extra vertical spacing
            user_msg = custom_body or f"Hello {name},\n\nPlease find attached your official invoice #{inv_num} for {product} ({formatted_amount}).\n\nThank you for your business!"
            user_msg = user_msg.replace('{{invoice_number}}', inv_num).replace('{{client_name}}', name).replace('{{amount}}', formatted_amount).replace('{{product}}', product).strip()

            if "<" in user_msg and ">" in user_msg:
                final_html = re.sub(r'>\s*\n+\s*<', '><', user_msg)
            else:
                final_html = user_msg

            # Inject hidden 1x1 tracking pixel inside body or at end
            host = self.headers.get('Host', 'zoho-invoicepulse.vercel.app')
            beacon_url = f"https://{host}/api/track?id={inv_num}&email={urllib.parse.quote(email)}"
            pixel_tag = f'<img src="{beacon_url}" width="1" height="1" alt="" style="display:none!important;" />'
            if "</body>" in final_html:
                final_html = final_html.replace("</body>", f"{pixel_tag}</body>")
            else:
                final_html += pixel_tag

            send_payload = {
                'send_attachment': True,
                'to_mail_ids': [email],
                'subject': subject,
                'body': final_html
            }

            # Try Zoho Invoice first, fallback to Books
            send_url = f"{api_domain}/invoice/v3/invoices/{inv_id}/email?organization_id={org_id}"
            req_send = urllib.request.Request(send_url, data=json.dumps(send_payload).encode('utf-8'), headers=headers, method='POST')
            try:
                with urllib.request.urlopen(req_send) as send_resp:
                    resp_data = json.loads(send_resp.read().decode('utf-8'))
                    self._send_json({'status': 'sent', 'invoiceNumber': inv_num, 'invoiceId': inv_id, 'zohoResponse': resp_data})
                    return
            except urllib.error.HTTPError as e:
                if e.code in (404, 400):
                    send_url = f"{api_domain}/books/v3/invoices/{inv_id}/email?organization_id={org_id}"
                    req_send = urllib.request.Request(send_url, data=json.dumps(send_payload).encode('utf-8'), headers=headers, method='POST')
                    with urllib.request.urlopen(req_send) as send_resp:
                        resp_data = json.loads(send_resp.read().decode('utf-8'))
                        self._send_json({'status': 'sent', 'invoiceNumber': inv_num, 'invoiceId': inv_id, 'zohoResponse': resp_data})
                        return
                raise

        except urllib.error.HTTPError as e:
            err_text = e.read().decode('utf-8', errors='ignore')
            self._send_json({'error': f"Zoho API Error ({e.code}): {err_text}"}, status=e.code)
        except Exception as e:
            self._send_json({'error': str(e)}, status=500)

    def _get_or_create_contact(self, api_domain, org_id, headers, name, email):
        last_error = "Unknown error"
        for service in ['invoice', 'books']:
            search_url = f"{api_domain}/{service}/v3/contacts?organization_id={org_id}&email={urllib.parse.quote(email)}"
            req_search = urllib.request.Request(search_url, headers=headers, method='GET')
            try:
                with urllib.request.urlopen(req_search) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    contacts = data.get('contacts', [])
                    if contacts:
                        return str(contacts[0]['contact_id'])
            except urllib.error.HTTPError as e:
                last_error = f"{service} GET error {e.code}: {e.read().decode('utf-8', errors='ignore')}"
            except Exception as e:
                last_error = f"{service} GET error: {str(e)}"

        # If contact not found, create new contact
        clean_name = name or email.split('@')[0]
        payload = {
            'contact_name': clean_name,
            'contact_persons': [{'first_name': clean_name, 'email': email, 'is_primary_contact': True}]
        }
        for service in ['invoice', 'books']:
            create_url = f"{api_domain}/{service}/v3/contacts?organization_id={org_id}"
            req_create = urllib.request.Request(create_url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
            try:
                with urllib.request.urlopen(req_create) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    return str(data['contact']['contact_id'])
            except urllib.error.HTTPError as e:
                last_error = f"{service} POST error {e.code}: {e.read().decode('utf-8', errors='ignore')}"
            except Exception as e:
                last_error = f"{service} POST error: {str(e)}"

        raise Exception(f"Could not create or retrieve contact in Zoho: {last_error}")

    def _create_invoice(self, api_domain, org_id, headers, customer_id, product, amount):
        last_error = "Unknown error"
        payload = {
            'customer_id': customer_id,
            'line_items': [{'name': product, 'rate': amount, 'quantity': 1}]
        }
        for service in ['invoice', 'books']:
            url = f"{api_domain}/{service}/v3/invoices?organization_id={org_id}"
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
            try:
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    return data['invoice']
            except urllib.error.HTTPError as e:
                last_error = f"{service} POST invoice error {e.code}: {e.read().decode('utf-8', errors='ignore')}"
            except Exception as e:
                last_error = f"{service} POST invoice error: {str(e)}"

        raise Exception(f"Could not create invoice in Zoho: {last_error}")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
