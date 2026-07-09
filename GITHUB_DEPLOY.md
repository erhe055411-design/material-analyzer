# 素材经营分析系统 - GitHub 部署指南

## 方案A：GitHub仓库托管（推荐）

本地能用只是半成品，把代码托管到GitHub才能持续迭代、团队协作。

### 步骤1：注册GitHub账号
1. 打开 https://github.com/
2. 点击 Sign up，使用邮箱注册
3. 验证邮箱，完成账号创建

### 步骤2：创建新仓库
1. 点击右上角 + → New repository
2. 仓库名填：`material-analyzer`
3. 描述填：`巨量投放团队素材经营分析系统`
4. 选择 **Public**（公开）或 **Private**（私有）
5. 不要勾选 "Initialize this repository with a README"
6. 点击 **Create repository**

### 步骤3：推送本地代码到GitHub

在你的终端（Terminal/iTerm/Git Bash）执行以下命令：

```bash
# 进入项目目录
cd /Users/test/Desktop/巨量ai工作引擎/material-analyzer

# 添加GitHub远程仓库（用你的用户名替换 YOUR_USERNAME）
git remote add origin https://github.com/YOUR_USERNAME/material-analyzer.git

# 推送代码
git branch -M main
git push -u origin main
```

### 步骤4：验证推送成功

1. 刷新 GitHub 仓库页面
2. 应该能看到所有代码文件（app.py、templates/、static/等）
3. README.md 会自动渲染在仓库首页

---

## 本地运行不受影响

代码托管到GitHub后，本地使用方式**完全不变**：

```bash
# 1. 进入项目目录
cd material-analyzer

# 2. 启动服务（和之前一样）
bash start.sh

# 3. 浏览器访问 http://localhost:8080
```

GitHub只是代码的"云备份"和"协作中心"，不影响本地运行。

---

## GitHub Pages 说明

**重要提示**：GitHub Pages 只能托管纯静态网站（HTML/CSS/JS），不支持 Python Flask 后端和 SQLite 数据库。

本项目有 Python 后端，所以**无法**通过 GitHub Pages 在线访问。

如需在线访问，可以考虑：
- **方案1**：部署到云服务器（阿里云/腾讯云/百度智能云）
- **方案2**：使用 PythonAnywhere / Heroku / Railway 等 PaaS 平台
- **方案3**：部署到公司内部服务器

---

## 团队协作

团队成员可以通过以下方式使用：

### 方式1：克隆仓库
```bash
git clone https://github.com/YOUR_USERNAME/material-analyzer.git
cd material-analyzer
pip3 install -r requirements.txt
python3 app.py
```

### 方式2：下载ZIP
1. 打开 GitHub 仓库页面
2. 点击绿色 "Code" 按钮
3. 选择 "Download ZIP"
4. 解压后运行

### 方式3：Fork + PR
1. 其他成员 Fork 你的仓库
2. 修改代码后提交 Pull Request
3. 你审核后合并

---

## 更新代码

当你修改了本地代码，想同步到 GitHub：

```bash
cd material-analyzer

# 1. 查看修改了哪些文件
git status

# 2. 添加所有修改
git add .

# 3. 提交（写一句修改说明）
git commit -m "fix: 修复了XX问题"

# 4. 推送到GitHub
git push origin main
```

---

## 常见问题

**Q: 推送时提示需要输入密码？**
A: GitHub已不支持密码验证，需要创建 Personal Access Token（PAT）：
   1. GitHub → Settings → Developer settings → Personal access tokens
   2. 生成 Token，复制保存
   3. 推送时输入 Token 代替密码

**Q: 数据库文件为什么没有上传到GitHub？**
A: 这是故意设计的！.gitignore 排除了 data/analyzer.db，防止敏感业务数据泄露。
   团队成员各自运行时会自动创建本地数据库。

**Q: 如何备份本地数据库？**
A: 复制 data/analyzer.db 文件到安全位置即可。恢复时覆盖回去。

**Q: 换了电脑怎么恢复数据？**
A: GitHub只存代码不存数据。需要手动复制 data/analyzer.db 到新电脑。

---

**最后更新时间**：2026-07-03
**版本**：v2.0
