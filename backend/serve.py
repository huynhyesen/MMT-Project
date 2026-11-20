"""Interactive entry point for the Windows parent launcher."""

import getpass
import os

import uvicorn


if __name__ == "__main__":
    if not os.getenv("MMT_PARENT_PASSWORD"):
        password = getpass.getpass("Đặt mật khẩu cho tài khoản parent: ")
        if not password:
            raise SystemExit("Cần đặt mật khẩu phụ huynh.")
        os.environ["MMT_PARENT_PASSWORD"] = password
    uvicorn.run("backend.app.main:app", host="0.0.0.0", port=8008)
