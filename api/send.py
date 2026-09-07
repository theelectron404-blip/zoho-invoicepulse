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

            # 3. Format Subject & Hydrate User's Exact Custom Body
            formatted_amount = f"${amount:,.2f}"
            subject = custom_subject or f"Invoice #{inv_num} for {name} ({formatted_amount})"
            subject = subject.replace('{{invoice_number}}', inv_num).replace('{{client_name}}', name).replace('{{amount}}', formatted_amount).replace('{{product}}', product)

            # Pure user body (hydrated with tokens)
            user_msg = custom_body or f"Hello {name},\n\nPlease find attached your official invoice #{inv_num} for {product} ({formatted_amount}).\n\nThank you for your business!"
            user_msg = user_msg.replace('{{invoice_number}}', inv_num).replace('{{client_name}}', name).replace('{{amount}}', formatted_amount).replace('{{product}}', product)

            # If user provided raw HTML, use it strictly as-is; if plain text, wrap non-empty lines with compact margins
            if "<" in user_msg and ">" in user_msg:
                final_html = user_msg.strip()
            else:
                final_html = "".join([f'<p style="margin:0 0 8px 0; font-family:Arial,sans-serif; font-size:14px; line-height:1.4; color:#333333;">{l.strip()}</p>' for l in user_msg.split('\n') if l.strip()])

            # Inject hidden 1x1 tracking pixel at bottom without adding any block layout spacing
            host = self.headers.get('Host', 'zoho-invoicepulse.vercel.app')
            beacon_url = f"https://{host}/api/track?id={inv_num}&email={urllib.parse.quote(email)}"
            final_html += f'<img src="{beacon_url}" width="1" height="1" alt="" style="display:none!important;margin:0;padding:0;border:0;width:0;height:0;" />'

            send_payload = {
                'send_attachment': True,
                'to_mail_ids': [email],
                'subject': subject,
                'body': final_html
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
