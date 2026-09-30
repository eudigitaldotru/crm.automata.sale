import argparse
import sys
import json
import time

"""
⚠️ MOCK IMPLEMENTATION (Stage 3)
Реальная отправка через Telegram Bot API будет реализована на Этапе 7
(блок "Биллинг и платежи").
До этого момента скрипт имитирует поведение для тестирования UI/API.
"""

EXIT_SUCCESS = 0
EXIT_INVOICE_NOT_FOUND = 10
EXIT_NO_INTERNET = 20
EXIT_TG_API_ERROR = 30
EXIT_INVALID_CHAT_ID = 40

def main():
    parser = argparse.ArgumentParser(description="Send invoice reminder via TG")
    parser.add_argument("--invoice", required=True, help="Invoice ID")
    parser.add_argument("--test-mode", action="store_true", help="Run in test mode")
    parser.add_argument("--fail-api", action="store_true", help="Simulate TG API failure")
    args = parser.parse_args()

    # Simulate delay
    time.sleep(1)

    if args.fail_api or args.invoice == "FAIL":
        print(json.dumps({"ok": False, "code": "TG_API_ERROR"}))
        sys.exit(EXIT_TG_API_ERROR)

    if args.invoice == "NO_INTERNET":
        print(json.dumps({"ok": False, "code": "NO_INTERNET"}))
        sys.exit(EXIT_NO_INTERNET)

    # Success case
    print(json.dumps({"ok": True, "msg_id": 12345}))
    sys.exit(EXIT_SUCCESS)

if __name__ == "__main__":
    main()
