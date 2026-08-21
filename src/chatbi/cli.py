"""ChatBI 命令行入口。"""

import sys

from chatbi.services.chatbi_service import ChatBISystem


def main() -> None:
    """命令行入口。"""
    system = ChatBISystem()

    print("=" * 60)
    print("ChatBI Text2SQL 系统")
    print("=" * 60)

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        result = system.run(question)
        _print_result(question, result)
        return

    print("\n请输入问题（输入 exit / quit / q 退出）：")
    while True:
        try:
            question = input("\n> ")
            if question.strip().lower() in ["exit", "quit", "q"]:
                break
            result = system.run(question)
            _print_result(question, result)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f"系统错误：{exc}")

    print("\n感谢使用！")


def _print_result(question: str, result: dict) -> None:
    """打印执行结果。"""
    print(f"\n问题：{question}")
    print(f"SQL：{result.get('sql', '')}")
    if result["success"]:
        print(f"\n{result['formatted']}")
    else:
        print(f"\n错误：{result['error']}")


if __name__ == "__main__":
    main()
