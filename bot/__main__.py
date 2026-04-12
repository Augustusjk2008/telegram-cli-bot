"""模块入口 (python -m bot)"""

import os
import sys

# 确保 refactoring/ 在 sys.path 中
_this_dir = os.path.dirname(os.path.abspath(__file__))
_package_root = os.path.dirname(_this_dir)
if _package_root not in sys.path:
    sys.path.insert(0, _package_root)

from bot.main import main

if __name__ == "__main__":
    main()
