#!/bin/bash
# DICOM CT ビューアー 起動スクリプト
# このファイルをダブルクリックして起動してください

cd "$(dirname "$0")"

# ライブラリ確認・インストール
python3 -c "import pydicom, PIL, numpy" 2>/dev/null || {
    echo "必要なライブラリをインストールしています..."
    pip3 install pydicom Pillow numpy
    echo "インストール完了"
}

echo "DICOM CT ビューアーを起動します..."
echo "ブラウザが自動的に開きます。"
echo "終了するにはこのウィンドウを閉じてください。"
echo ""

python3 dicom_viewer_web.py
