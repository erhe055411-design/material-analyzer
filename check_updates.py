#!/usr/bin/env python3
"""
一键更新脚本：将沙箱中的修改同步到本地项目
用法：python3 sync_updates.py
"""
import os, shutil

BASE = os.path.dirname(os.path.abspath(__file__))

files = {
    'templates/index.html': os.path.join(BASE, 'templates', 'index.html'),
    'static/css/app.css': os.path.join(BASE, 'static', 'css', 'app.css'),
    'static/js/app.js': os.path.join(BASE, 'static', 'js', 'app.js'),
    'app.py': os.path.join(BASE, 'app.py'),
}

print("=" * 60)
print("素材分析系统 - 全局AI助手更新脚本")
print("=" * 60)

for name, path in files.items():
    print(f"\n📁 检查: {name}")
    if not os.path.exists(path):
        print(f"   ❌ 文件不存在: {path}")
        continue
    
    # 简单验证关键标记存在
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否包含新代码的标记
    if name == 'templates/index.html':
        has_new = 'ai-assistant-fab' in content
        print(f"   {'✅ 已包含全局AI助手' if has_new else '⚠️ 可能未包含新代码'}")
    elif name == 'static/css/app.css':
        has_new = '.ai-assistant-fab' in content
        print(f"   {'✅ 已包含AI助手样式' if has_new else '⚠️ 可能未包含新样式'}")
    elif name == 'static/js/app.js':
        has_new = 'openGlobalAIAssistant' in content
        print(f"   {'✅ 已包含AI助手逻辑' if has_new else '⚠️ 可能未包含新逻辑'}")
    elif name == 'app.py':
        has_new = 'ai_chat_general' in content
        print(f"   {'✅ 已包含通用AI接口' if has_new else '⚠️ 可能未包含新接口'}")

print("\n" + "=" * 60)
print("如果上面4个文件都显示✅，说明修改已在本目录生效")
print("如果显示⚠️，请确认你运行的是项目根目录的脚本")
print("\n下一步：")
print("1. 确保 .env 配置为 DeepSeek:")
print("   AI_API_KEY=你的DeepSeekKey")
print("   AI_BASE_URL=https://api.deepseek.com/v1")
print("   AI_MODEL=deepseek-chat")
print("2. 重启服务: lsof -t -i :8080 | xargs kill -9; python3 app.py")
print("3. 浏览器访问 http://localhost:8080")
print("=" * 60)
