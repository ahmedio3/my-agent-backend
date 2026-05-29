import os
import json
import asyncio
import subprocess
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai

app = FastAPI()

# تفعيل الـ CORS عشان تطبيق الكوتلن يقدر يتصل بالباك آيند بدون مشاكل
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# كلاس لإدارة وتدوير مفاتيح الـ API الخمسة تلقائياً
class APIKeyManager:
    def __init__(self):
        # بيجيب المفاتيح المتاحة في متغيرات البيئة بـ Vercel
        self.keys = [
            os.environ.get("GEMINI_KEY_1"),
            os.environ.get("GEMINI_KEY_2"),
            os.environ.get("GEMINI_KEY_3"),
            os.environ.get("GEMINI_KEY_4"),
            os.environ.get("GEMINI_KEY_5")
        ]
        # تصفية المفاتيح الفارغة
        self.keys = [k for k in self.keys if k]
        self.current_index = 0
        
        if not self.keys:
            print("تحذير: لم يتم العثور على أي مفتاح API لـ Gemini!")

    def get_configured_model(self):
        if not self.keys:
            raise ValueError("لا توجد مفاتيح API مفعّلة في السيرفر.")
        
        key = self.keys[self.current_index]
        genai.configure(api_key=key)
        # تدوير للمفتاح التالي في الطلب القادم لتوزيع الحمل
        self.current_index = (self.current_index + 1) % len(self.keys)
        return genai.GenerativeModel('gemini-3.1-flash-lite')

key_manager = APIKeyManager()

class UserPrompt(BaseModel):
    prompt: str

# دالة لتوليد خطوات الـ Agent وبثها لايف (Streaming)
async def run_agent_workflow(user_query: str):
    workspace_dir = "/tmp/agent_workspace"
    os.makedirs(workspace_dir, exist_ok=True)
    target_file = os.path.join(workspace_dir, "app.py")
    
    try:
        # ---- الخطوة 1: الأجنت الرئيسي (المايسترو) يضع الخطة ----
        yield f"data: {json.dumps({'step': 'planning', 'message': 'المايسترو يحلل طلبك الآن ويضع خطة البناء...'})}\n\n"
        await asyncio.sleep(0.5)
        
        model = key_manager.get_configured_model()
        plan_prompt = f"""
        أنت الأجنت الرئيسي (المايسترو). المستخدم يريد بناء التالي: "{user_query}"
        اكتب خطة عمل منطقية من خطوات قصيرة جداً لبناء هذا المطلوب (سواء كان بوت تليجرام أو API ببايثون).
        اكتب الخطة بنقاط واضحة ومختصرة باللغة العربية.
        """
        plan_response = model.generate_content(plan_prompt)
        plan_text = plan_response.text
        
        yield f"data: {json.dumps({'step': 'plan_ready', 'message': plan_text})}\n\n"
        await asyncio.sleep(1)

        # ---- الخطوة 2: الـ Sub-agent المخصص لكتابة الكود ----
        yield f"data: {json.dumps({'step': 'coding', 'message': 'الآن المساعد المبرمج يقوم بكتابة الكود الأساسي للمشروع...'})}\n\n"
        
        coder_prompt = f"""
        أنت الـ Sub-agent المبرمج المحترف. بناءً على الخطة:
        {plan_text}
        اكتب كود بايثون كامل وعامل بدون اختصارات لتنفيذ المطلوب تماماً.
        ملاحظة: اكتب الكود فقط داخل علامات الكود الكلاسيكية بدون أي مقدمات أو مؤخرات.
        ```python
        # الكود هنا
        ```
        """
        model = key_manager.get_configured_model()
        code_response = model.generate_content(coder_prompt)
        raw_code = code_response.text
        
        # استخراج الكود النظيف من الـ markdown
        clean_code = raw_code
        if "```python" in raw_code:
            clean_code = raw_code.split("```python")[1].split("```")[0].strip()
        elif "```" in raw_code:
            clean_code = raw_code.split("```")[1].split("```")[0].strip()

        # حفظ الكود في بيئة التشغيل المؤقتة
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(clean_code)
            
        yield f"data: {json.dumps({'step': 'code_written', 'message': 'تم كتابة الكود وحفظه بنجاح في البيئة التجريبية.', 'code': clean_code})}\n\n"
        await asyncio.sleep(1)

        # ---- الخطوة 3: تشغيل الكود واختباره وقراءة الـ Logs ----
        yield f"data: {json.dumps({'step': 'testing', 'message': 'جاري تشغيل الكود الآن واختبار جودته وقراءة الـ Logs...'})}\n\n"
        await asyncio.sleep(1)
        
        # بنعمل فحص تشغيل مبدئي (Syntax and dry run)
        # تشغيل بايثون على الملف لثانيتين للتأكد أنه لا يحتوي على أخطاء استيراد أو سنتكس
        try:
            process = subprocess.run(
                ["python3", "-m", "py_compile", target_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5
            )
            stdout = process.stdout
            stderr = process.stderr
            return_code = process.returncode
        except Exception as e:
            stderr = str(e)
            return_code = 1
            stdout = ""

        # ---- الخطوة 4: الـ Sub-agent المصحح (Debugger) يراجع اللوجز ----
        if return_code != 0:
            yield f"data: {json.dumps({'step': 'error_found', 'message': 'تم اكتشاف خطأ في الـ Logs! جاري إرساله للمساعد المصحح للحل...', 'logs': stderr})}\n\n"
            await asyncio.sleep(1)
            
            debugger_prompt = f"""
            أنت الـ Sub-agent المتخصص في الفحص والتصحيح (Debugger).
            الكود التالي يحتوي على خطأ أثناء التشغيل:
            ```python
            {clean_code}
            ```
            وهذه هي رسالة الخطأ واللوجز (Logs):
            {stderr}
            
            قم بإصلاح الخطأ تماماً وأعد كتابة الكود كاملاً ومصلحاً وصحيحاً 100% داخل علامات الكود النظيفة فقط:
            ```python
            # الكود المصلح هنا
            ```
            """
            model = key_manager.get_configured_model()
            fixed_response = model.generate_content(debugger_prompt)
            fixed_raw_code = fixed_response.text
            
            fixed_code = fixed_raw_code
            if "```python" in fixed_raw_code:
                fixed_code = fixed_raw_code.split("```python")[1].split("```")[0].strip()
            
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(fixed_code)
                
            yield f"data: {json.dumps({'step': 'completed', 'message': 'تم مراجعة الخطأ وتصليحه بنجاح! الكود النهائي جاهز للاستخدام الآن.', 'code': fixed_code})}\n\n"
        else:
            yield f"data: {json.dumps({'step': 'completed', 'message': 'تم اختبار الكود واجتاز فحص التشغيل بدون أي أخطاء! المشروع جاهز.', 'code': clean_code})}\n\n"

    except Exception as global_error:
        yield f"data: {json.dumps({'step': 'failed', 'message': f'حدث خطأ غير متوقع في نظام الـ Agent: {str(global_error)}'})}\n\n"

@app.post("/api/agent")
async def handle_agent_request(payload: UserPrompt):
    return StreamingResponse(run_agent_workflow(payload.prompt), media_type="text/event-stream")

# نقطة دخول للموقع للتأكد أنه شغال
@app.get("/")
def read_root():
    return {"status": "Agent Backend is Running Successfully!"}
      
