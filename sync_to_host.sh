#!/usr/bin/env bash
set -e

echo "🚀 开始编译小程序并同步至 Windows D:\\zhilian-mp ..."
pnpm --dir miniprogram run build:mp-weixin

mkdir -p /mnt/d/zhilian-mp
rm -rf /mnt/d/zhilian-mp/*
cp -ru miniprogram/dist/build/mp-weixin/* /mnt/d/zhilian-mp/

echo "✅ 打包并同步完成！路径：D:\\zhilian-mp"
