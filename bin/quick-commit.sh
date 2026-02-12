#!/bin/bash
# 快速 Git 提交脚本
# 使用方法: bash quick-commit.sh "提交信息"

if [ -z "$1" ]; then
    echo "用法: bash quick-commit.sh \"提交信息\""
    echo "示例: bash quick-commit.sh \"修复bug\""
    exit 1
fi

git add -A
git commit -m "$1"
echo "✓ 已提交: $1"

# 可选：自动推送到远程
# git push
