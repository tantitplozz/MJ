import asyncio
import json
import os
import re
from contextlib import AsyncExitStack
from dotenv import load_dotenv
from tenacity import retry, wait_fixed, stop_after_attempt

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

BOOKING_URL = os.environ["BOOKING_URL"].strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:11434/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "ollama")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "hf.co/mradermacher/Dolphin3.0-R1-Mistral-24B-GGUF:Q4_K_M")
VISION_MODEL = os.getenv("VISION_MODEL", "llama3.2-vision")

GUEST = {
    "email": os.getenv("GUEST_EMAIL", ""),
    "phone": os.getenv("GUEST_PHONE", ""),
    "first": os.getenv("GUEST_FIRST_NAME", ""),
    "last": os.getenv("GUEST_LAST_NAME", ""),
    "addr": os.getenv("GUEST_ADDRESS", ""),
    "city": os.getenv("GUEST_CITY", ""),
    "country": os.getenv("GUEST_COUNTRY", "TH"),
}

CARD = {
    "number": os.getenv("CARD_NUMBER", ""),
    "exp_m": os.getenv("CARD_EXP_MONTH", ""),
    "exp_y": os.getenv("CARD_EXP_YEAR", ""),
    "cvv": os.getenv("CARD_CVV", ""),
    "holder": os.getenv("CARD_HOLDER", ""),
}

PLAYWRIGHT_CMD = os.getenv("PLAYWRIGHT_MCP_CMD", "npx").split()
PLAYWRIGHT_ARGS = os.getenv("PLAYWRIGHT_MCP_ARGS", "-y @executeautomation/playwright-mcp-server").split()

JS_CLICK_RESERVE = r"""
(() => {
  const buttons = Array.from(document.querySelectorAll('button, a'));
  const targets = buttons.filter(el => /reserve|book|จอง/i.test(el.textContent||''));
  if (targets[0]) { targets[0].click(); return 'clicked'; }
  const submit = buttons.find(el => /continue|next|ถัดไป|ดำเนินการต่อ/i.test(el.textContent||''));
  if (submit) { submit.click(); return 'clicked-next'; }
  return 'not-found';
})()
"""

JS_FILL_BY_LABEL = """
(arg) => {
  const {labelRegex, value} = arg;
  const rx = new RegExp(labelRegex, 'i');
  const labels = Array.from(document.querySelectorAll('label'));
  for (const lb of labels) {
    if (rx.test(lb.textContent||'')) {
      const id = lb.getAttribute('for');
      let input = id ? document.getElementById(id) : lb.querySelector('input,textarea,select');
      if (input) { input.focus(); input.value = value; input.dispatchEvent(new Event('input', {bubbles:true})); return true; }
    }
  }
  const inputs = Array.from(document.querySelectorAll('input[placeholder],textarea[placeholder]'));
  for (const i of inputs) {
    if (rx.test(i.getAttribute('placeholder')||'')) { i.focus(); i.value = value; i.dispatchEvent(new Event('input',{bubbles:true})); return true; }
  }
  return false;
}
"""

JS_FIND_IFRAMES = r"""
(() => Array.from(document.querySelectorAll('iframe')).map((f,i)=>({i, name:f.name||'', src:f.src||''})))()
"""

@retry(wait=wait_fixed(2), stop=stop_after_attempt(5))
async def call(session: ClientSession, tool: str, args: dict):
    return await session.call_tool(tool, args)

async def main():
    async with AsyncExitStack() as stack:
        server_params = StdioServerParameters(command=PLAYWRIGHT_CMD[0], args=PLAYWRIGHT_ARGS)
        stdio = await stack.enter_async_context(stdio_client(server_params))
        read, write = stdio
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        # 1) navigate
        await call(session, "Playwright_navigate", {
            "url": BOOKING_URL, "headless": False, "width": 1280, "height": 900
        })

        # 2) click reserve/book
        await call(session, "Playwright_evaluate", {"script": JS_CLICK_RESERVE})

        # 3) fill email first
        if GUEST["email"]:
            await call(session, "Playwright_evaluate", {
                "script": "("+JS_FILL_BY_LABEL+")",
                "arg": {"labelRegex": "email|อีเมล", "value": GUEST["email"]}
            })

        # 4) continue
        await call(session, "Playwright_evaluate", {"script": JS_CLICK_RESERVE})

        # 5) fill name, phone, address
        mapping = [
            ("first name|ชื่อ(?!ผู้ถือ)|given", GUEST["first"]),
            ("last name|นามสกุล|family", GUEST["last"]),
            ("phone|โทร", GUEST["phone"]),
            ("address|ที่อยู่", GUEST["addr"]),
            ("city|เมือง", GUEST["city"]),
        ]
        for label_rx, val in mapping:
            if val:
                await call(session, "Playwright_evaluate", {
                    "script": "("+JS_FILL_BY_LABEL+")",
                    "arg": {"labelRegex": label_rx, "value": val}
                })

        # 6) proceed again
        await call(session, "Playwright_evaluate", {"script": JS_CLICK_RESERVE})

        # 7) payment attempt if CARD set; Booking often uses iframes
        if CARD["number"] and CARD["exp_m"] and CARD["exp_y"] and CARD["cvv"]:
            frames = await call(session, "Playwright_evaluate", {"script": JS_FIND_IFRAMES})
            # naive guesses for common PSPs
            candidate_iframes = []
            try:
                items = json.loads(frames.content[0].text)
                for f in items:
                    s = (f.get('src') or '').lower()
                    if any(k in s for k in ["card", "payment", "adyen", "braintree", "stripe"]):
                        candidate_iframes.append(f)
            except Exception:
                pass

            # try simple selectors first (if not inside iframes)
            for label_rx, val in [("card number|หมายเลขบัตร", CARD["number"]), ("name on card|ชื่อผู้ถือ", CARD["holder"])]:
                await call(session, "Playwright_evaluate", {
                    "script": "("+JS_FILL_BY_LABEL+")",
                    "arg": {"labelRegex": label_rx, "value": val}
                })

            # try iframes generically
            for f in candidate_iframes:
                sel = f"iframe[name='{f.get('name','')}']" if f.get('name') else None
                if sel:
                    for css, val in [("input[name*='cardnumber'], input[autocomplete*='cc-number']", CARD["number"]),
                                     ("input[name*='exp'], input[autocomplete*='cc-exp']", f"{CARD['exp_m']}/{CARD['exp_y'][-2:]}"),
                                     ("input[name*='cvc'], input[autocomplete*='cc-csc'], input[name*='cvv']", CARD["cvv"])]:
                        await call(session, "Playwright_iframe_fill", {"iframeSelector": sel, "selector": css, "value": val})

            # final continue
            await call(session, "Playwright_evaluate", {"script": JS_CLICK_RESERVE})

        # 8) save PDF proof
        await call(session, "playwright_save_as_pdf", {"outputPath": os.getcwd(), "filename": "booking-confirmation.pdf"})

        print("done")

if __name__ == "__main__":
    asyncio.run(main())