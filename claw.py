#!/usr/bin/env python3#!/usr/bin/env python3
from openai import OpenAI
import os, sys, re, subprocess
from pathlib import Path

# ================= 配置区域 =================
CONFIG = {
    "api_key": "sk-b897bb331e9f448aac1d089118da1ec5",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-plus",
    "agent_file": "Agent.md",
    "skills_dir": "skills",
    "timeout": 30,
}
# ===========================================

def extract_skill(text):
    """提取 '调用 XXX skill' 中的 XXX"""
    m = re.search(r'调用\s+(\S+)\s+skill', text, re.I)
    return m.group(1).strip() if m else None

def load_skill(name):
    """加载 skills/{name}/{name}.md"""
    path = Path(CONFIG["skills_dir"]) / name / f"{name}.md"
    return path.read_text(encoding='utf-8') if path.exists() else None

def main():
    if not CONFIG["api_key"]:
        print("错误：未设置 DASHSCOPE_API_KEY"); sys.exit(1)

    agent_prompt = open(CONFIG["agent_file"]).read()
    client = OpenAI(api_key=CONFIG["api_key"], base_url=CONFIG["base_url"])
    
    with client:
        messages = [{"role": "system", "content": agent_prompt}]
        active_skill = None  # 追踪当前激活的技能
        
        while True:
            try:
                user_input = input("User: ")
                if not user_input.strip():
                    continue
                
                # 检测技能调用
                skill_name = extract_skill(user_input)
                if skill_name:
                    skill_content = load_skill(skill_name)
                    if skill_content:
                        messages.append({
                            "role": "system",
                            "content": f"## 激活技能：{skill_name}\n{skill_content}"
                        })
                        user_input = re.sub(r'调用\s+\S+\s+skill\s*', '', user_input, flags=re.I).strip()
                        print(f"[加载技能]: {skill_name}")
                        active_skill = skill_name
                    else:
                        print(f"[警告] 未找到技能：{skill_name}")
                
                messages.append({"role": "user", "content": user_input})
                
                # 循环处理 AI 回复
                while True:
                    response = client.chat.completions.create(
                        model=CONFIG["model"],
                        messages=messages,
                        timeout=CONFIG["timeout"]
                    )
                    reply = response.choices[0].message.content
                    print(f"\n[AI 回复]:\n{reply}\n")
                    messages.append({"role": "assistant", "content": reply})
                    
                    # 检查是否完成
                    if "[完成]" in reply:
                        print("任务完成\n")
                        active_skill = None  # 重置技能状态
                        break
                    
                    # 检查并执行命令
                    if "[命令]" in reply:
                        cmd = reply.split("[命令]")[1].strip().split('\n')[0].strip()
                        cmd = cmd.replace('```', '').replace('`', '').strip()
                        print(f"[执行命令]: {cmd}")
                        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                        output = result.stdout if result.stdout else result.stderr
                        print(f"[执行结果]:\n{output}\n")
                        messages.append({"role": "user", "content": f"[执行完成]\n{output}"})
                        continue
                    
                    # 技能模式下 接受技能自定义输出格式
                    if active_skill:
                        # 检查是否包含技能标记（如 [计算]、[天气]、[搜索] 等）
                        if re.search(r'\[\S+\]', reply):
                            print(f"[技能输出]: {active_skill}")
                            print("任务完成\n")
                            active_skill = None  # 重置技能状态
                            break
                    
                    # 若格式不正确 就提醒 AI
                    print("AI 未按格式回复，提醒重新生成...")
                    messages.append({
                        "role": "user",
                        "content": "请严格按照格式回复：[命令]XXX 或 [完成]XXX"
                    })
                    
            except KeyboardInterrupt:
                print("\n已退出"); break
            except:
                raise

if __name__ == "__main__":
    main()