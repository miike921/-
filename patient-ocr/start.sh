#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  患者一覧 OCR アプリ 起動中"
echo "  ブラウザで以下を開いてください："
echo "  http://localhost:3000"
echo "  終了: Ctrl+C"
echo "========================================"
python3 -m http.server 3000 --directory public
