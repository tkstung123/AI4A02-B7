import streamlit as st
import pandas as pd
import google.generativeai as genai
import io
import json
import os
from dotenv import load_dotenv

# Load các biến môi trường từ .env
load_dotenv()

# Tự động đồng bộ credentials.json sang .streamlit/secrets.toml nếu chạy ở local
if os.path.exists("credentials.json") and not os.path.exists(".streamlit/secrets.toml"):
    try:
        os.makedirs(".streamlit", exist_ok=True)
        with open("credentials.json", "r", encoding="utf-8") as f:
            creds = json.load(f)
        toml_content = "[connections.gsheets]\n"
        for k, v in creds.items():
            if k == "private_key":
                toml_content += f'private_key = """{v}"""\n'
            elif isinstance(v, str):
                escaped_v = v.replace('"', '\\"')
                toml_content += f'{k} = "{escaped_v}"\n'
            else:
                toml_content += f'{k} = {json.dumps(v)}\n'
        with open(".streamlit/secrets.toml", "w", encoding="utf-8") as f:
            f.write(toml_content)
    except Exception as e:
        pass

# Page configuration
st.set_page_config(page_title="Real Estate Lead Scoring AI", page_icon="🏡", layout="wide")

# Load CSS for better aesthetics
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 5px;
        height: 3em;
        background-color: #007bff;
        color: white;
        font-weight: bold;
    }
    .stDownloadButton>button {
        width: 100%;
        background-color: #28a745;
        color: white;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)

# Helper Functions
def load_data_from_url(sheet_url):
    """Tải dữ liệu từ Google Sheet (ưu tiên dùng Streamlit Secrets, sau đó đến credentials.json)"""
    try:
        secret_dict = None
        
        # 1. Ưu tiên đọc từ Streamlit Secrets (connections.gsheets)
        if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
            secret_dict = dict(st.secrets["connections"]["gsheets"])
        # 2. Dự phòng đọc từ file credentials.json cục bộ
        elif os.path.exists("credentials.json"):
            with open("credentials.json", "r", encoding="utf-8") as f:
                secret_dict = json.load(f)
                
        # Nếu tìm thấy thông tin xác thực, kết nối qua gspread
        if secret_dict:
            import gspread
            from google.oauth2.service_account import Credentials
            
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            
            # Chuẩn hóa private key (tránh lỗi định dạng PEM khi copy-paste)
            if "private_key" in secret_dict and isinstance(secret_dict["private_key"], str):
                pk_cleaned = secret_dict["private_key"].replace("\\n", "\n")
                pk_lines = [line.strip() for line in pk_cleaned.split("\n") if line.strip()]
                secret_dict["private_key"] = "\n".join(pk_lines)
                
            creds = Credentials.from_service_account_info(secret_dict, scopes=scopes)
            client = gspread.authorize(creds)
            
            sheet = client.open_by_url(sheet_url)
            worksheet = sheet.get_worksheet(0)
            
            # Đọc dữ liệu thành DataFrame
            all_values = worksheet.get_all_values()
            if not all_values:
                return pd.DataFrame()
            
            headers = all_values[0]
            rows = all_values[1:]
            return pd.DataFrame(rows, columns=headers)
        else:
            # Nếu không cấu hình credentials, tải công khai dạng CSV
            if "/edit" in sheet_url:
                csv_url = sheet_url.split("/edit")[0] + "/export?format=csv"
            elif "/pubhtml" in sheet_url:
                csv_url = sheet_url.split("/pubhtml")[0] + "/pub?output=csv"
            else:
                csv_url = sheet_url
            return pd.read_csv(csv_url)
    except Exception as e:
        raise ValueError(
            f"Không thể đọc Google Sheet. "
            f"Vui lòng đảm bảo cấu hình Streamlit Secrets (connections.gsheets) hoặc file credentials.json hợp lệ "
            f"và tài khoản Service Account đã có quyền Viewer trên Sheet. "
            f"Lỗi chi tiết: {e}"
        )

def load_scoring_skill():
    """Tải tiêu chí chấm điểm từ file markdown"""
    try:
        with open("lead_scoring_skill.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Scoring criteria file not found. Please ensure lead_scoring_skill.md exists."

def score_lead(model, lead_data):
    """Gửi một lead đến Gemini để chấm điểm"""
    lead_json = lead_data.to_json(force_ascii=False)
    prompt = f"Evaluate this lead and return a JSON object as specified in the instructions:\n{lead_json}"
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except Exception as e:
        return {"score": 0, "category": "Potential", "reasoning": f"Lỗi AI: {str(e)}"}

def keyword_scoring(description):
    """Chấm điểm nhanh dựa trên từ khóa (Rule-based)"""
    score = 0
    reasons = []
    description = str(description).lower()
    
    # VIP Keywords
    vip_keywords = {
        "20 tỷ": "Ngân sách lớn (>= 20 tỷ)",
        "tài chính mạnh": "Tài chính mạnh",
        "không thành vấn đề": "Ngân sách linh hoạt",
        "biệt thự": "Loại hình cao cấp (Biệt thự)",
        "penthouse": "Loại hình cao cấp (Penthouse)",
        "shophouse": "Loại hình cao cấp (Shophouse)",
        "đất công nghiệp": "Quỹ đất lớn",
        "văn phòng": "Diện tích văn phòng lớn",
        "quận 1": "Vị trí đắc địa (Quận 1)",
        "ven sông": "Vị trí đắc địa (Ven sông)",
        "vinhomes": "Vị trí đắc địa (Vinhomes)",
        "phú mỹ hưng": "Vị trí đắc địa (Phú Mỹ Hưng)",
        "chủ doanh nghiệp": "Đối tượng khách hàng VIP",
        "nhà đầu tư": "Nhà đầu tư chuyên nghiệp",
        "mua sỉ": "Mua sỉ/số lượng lớn",
        "pháp lý chuẩn": "Yêu cầu pháp lý minh bạch",
        "sổ hồng": "Có sổ hồng riêng",
        "đàm phán": "Thiện chí gặp trực tiếp"
    }
    
    # Trash Keywords
    trash_keywords = {
        "nhầm số": "Nhầm số/Dữ liệu cũ",
        "không có nhu cầu": "Không có nhu cầu thực",
        "dữ liệu cũ": "Dữ liệu cũ",
        "hỏi giá cho vui": "Không thiện chí",
        "chưa có ý định mua": "Chưa có ý định mua",
        "bảo hiểm": "Spam/Quảng cáo bảo hiểm",
        "vay vốn": "Spam/Quảng cáo vay vốn",
        "thuê bao": "Không liên lạc được",
        "không bắt máy": "Không liên lạc được",
        "không phản hồi": "Không phản hồi Zalo/SĐT",
        "phi thực tế": "Yêu cầu phi thực tế",
        "giá 1 tỷ": "Ngân sách phi thực tế ở trung tâm",
        "giá 2 triệu": "Ngân sách thuê phi thực tế",
        "spam": "Spam/Quảng cáo"
    }

    found_vip = [v for k, v in vip_keywords.items() if k in description]
    found_trash = [v for k, v in trash_keywords.items() if k in description]

    if found_vip:
        score += 50
        reasons.extend(found_vip)
    if found_trash:
        score -= 50
        reasons.extend(found_trash)
    
    category = "VIP" if score >= 50 else "Trash" if score <= -50 else "Potential"
    reasoning = "Từ khóa tìm thấy: " + ", ".join(reasons) if reasons else "Nhu cầu cơ bản / Cần tư vấn thêm"
    
    return {"score": score, "category": category, "reasoning": reasoning}

# Sidebar - Settings
st.sidebar.title("⚙️ Cấu hình")
api_key = st.sidebar.text_input("Gemini API Key", type="password", value=os.getenv("GEMINI_API_KEY", ""))
if not api_key:
    st.sidebar.info("💡 Điền Gemini API Key ở trên để sử dụng chế độ AI. Nếu không điền, bạn vẫn có thể sử dụng chế độ chấm điểm bằng Từ khóa (Rule-based).")

st.sidebar.divider()
with st.sidebar.expander("📄 Xem tiêu chí chấm điểm"):
    st.markdown(load_scoring_skill())

# Main UI
st.title("🏡 Real Estate Lead Scoring AI")
st.markdown("Hệ thống tự động đánh giá và phân loại khách hàng tiềm năng bằng trí tuệ nhân tạo.")

# Step 1: Load and Preview Data
st.subheader("1. Dữ liệu khách hàng")

# Cho phép chọn nguồn dữ liệu (Google Sheet hoặc tải tệp trực tiếp)
data_source = st.radio("Chọn nguồn nhập dữ liệu khách hàng:", ["Google Sheet Link", "Tải lên tệp CSV/Excel từ máy tính"], horizontal=True)

if data_source == "Google Sheet Link":
    sheet_url = st.text_input("Nhập Google Sheet URL:", 
                             value="https://docs.google.com/spreadsheets/d/1PtYHhTapnRp8bOVYCxkAaEb37G_7iva99xnmoO-lvG0/edit?usp=sharing",
                             key="sheet_url")
    if st.button("📥 Tải dữ liệu từ Google Sheet"):
        try:
            df = load_data_from_url(sheet_url)
            st.session_state['df_leads'] = df
            if 'scored_df' in st.session_state:
                del st.session_state['scored_df']
            st.success(f"Đã tải {len(df)} khách hàng thành công từ Google Sheet!")
        except Exception as e:
            st.error(f"Lỗi khi tải dữ liệu từ Google Sheet: {e}")
else:
    uploaded_file = st.file_uploader("Tải lên tệp danh sách khách hàng (chấp nhận .csv, .xlsx):", type=["csv", "xlsx"])
    if uploaded_file is not None:
        try:
            if uploaded_file.name.endswith('.csv'):
                df = pd.read_csv(uploaded_file)
            else:
                df = pd.read_excel(uploaded_file)
            st.session_state['df_leads'] = df
            if 'scored_df' in st.session_state:
                del st.session_state['scored_df']
            st.success(f"Đã tải {len(df)} khách hàng thành công từ tệp của bạn!")
        except Exception as e:
            st.error(f"Lỗi khi tải dữ liệu từ tệp tin: {e}")

# Hiển thị dữ liệu gốc và các bước tiếp theo khi dữ liệu đã được nạp
if 'df_leads' in st.session_state:
    st.dataframe(st.session_state['df_leads'], use_container_width=True)

    # Step 2: Scoring
    st.divider()
    st.subheader("2. Chấm điểm")
    
    col1, col2 = st.columns(2)
    with col1:
        use_ai = st.toggle("Sử dụng AI (Cần Gemini Key)", value=True)
    with col2:
        start_button = st.button("🚀 Bắt đầu chấm điểm")
    
    if start_button:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(st.session_state['df_leads'])

        if use_ai:
            if not api_key:
                st.error("❌ Vui lòng nhập Gemini API Key để sử dụng chế độ AI.")
                st.stop()
            genai.configure(api_key=api_key)
            skill_content = load_scoring_skill()
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                system_instruction=f"You are a professional Lead Scoring Assistant for Real Estate. Use the following criteria:\n\n{skill_content}"
            )
        
        for i, (index, row) in enumerate(st.session_state['df_leads'].iterrows()):
            status_text.text(f"Đang xử lý: {row.get('ten_khach', 'Khách hàng')} ({i+1}/{total})")
            
            if use_ai:
                score_result = score_lead(model, row)
            else:
                score_result = keyword_scoring(row.get('nhu_cau_mo_ta', ''))
            
            # Combine original data with results (thêm các cột Score, Category, Reasoning)
            combined = row.to_dict()
            combined.update({
                "Score": int(score_result.get("score", 0)),
                "Category": score_result.get("category", "Potential"),
                "Reasoning": score_result.get("reasoning", "")
            })
            results.append(combined)
            progress_bar.progress((i + 1) / total)
            
        st.session_state['scored_df'] = pd.DataFrame(results)
        st.success("✅ Đã hoàn thành chấm điểm!")

    if 'scored_df' in st.session_state:
        st.subheader("📊 Kết quả phân loại")
        
        # Add color coding to Category
        def color_category(val):
            color = '#ff4b4b' if val == 'Trash' else '#28a745' if val == 'VIP' else '#ffa500'
            return f'color: {color}; font-weight: bold'
        
        st.dataframe(st.session_state['scored_df'].style.map(color_category, subset=['Category']), use_container_width=True)
        
        # Step 3: Export
        st.divider()
        st.subheader("3. Xuất dữ liệu")
        
        # Tạo file CSV in memory (UTF-8-sig để chống lỗi font tiếng Việt khi mở bằng Excel)
        csv_data = st.session_state['scored_df'].to_csv(index=False, encoding='utf-8-sig')
        
        # Tạo file Excel in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state['scored_df'].to_excel(writer, index=False, sheet_name='Scored Leads')
        excel_data = output.getvalue()
        
        col_dl_csv, col_dl_excel = st.columns(2)
        with col_dl_csv:
            st.download_button(
                label="📥 Tải về file CSV kết quả (.csv)",
                data=csv_data,
                file_name="leads_scored_results.csv",
                mime="text/csv"
            )
        with col_dl_excel:
            st.download_button(
                label="📥 Tải về file Excel kết quả (.xlsx)",
                data=excel_data,
                file_name="leads_scored_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
else:
    st.info("Nhấn nút 'Tải dữ liệu' để bắt đầu.")
