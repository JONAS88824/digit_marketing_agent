r"""极简测试运行器：不依赖 pytest，也能被 pytest 直接收集。

为什么自己写：这个项目不想为了跑几个断言就引入 pytest 依赖。
函数名以 test_ 开头的写法同时兼容 pytest，将来想装 pytest 也不用改测试。

用法（在测试文件末尾）：
    if __name__ == "__main__":
        raise SystemExit(run(globals()))
"""


def run(namespace: dict) -> int:
    """跑 namespace 里所有 test_ 开头的函数，返回进程退出码（0 = 全通过）。"""
    tests = [
        value
        for name, value in sorted(namespace.items())
        if name.startswith("test_") and callable(value)
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {test.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001 - 自检脚本要看到全部错误
            failed += 1
            print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok    {test.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0
