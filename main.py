"""兼容原有命令行入口。"""

from chatbi.cli import _print_result, main
from chatbi.services.chatbi_service import ChatBISystem

__all__ = ["ChatBISystem", "main"]


if __name__ == "__main__":
    main()
