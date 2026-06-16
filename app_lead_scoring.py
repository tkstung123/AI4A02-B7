import streamlit as st
import pandas as pd
import google.generativeai as genai
import io
import json
import os
from dotenv import load_dotenv

# Tải các cấu hình biến môi trường từ file .env
load_dotenv()

# Cấu hình giao diện Streamlit
st.set_page_config(
    page_title="AI Lead Scoring - Bất Động Sản",
    page_icon="🏡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Thiết kế giao diện premium với Custom CSS
st.markdown("""
    <style>
    /* Nhúng font chữ Google Font */
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&display=swap');
    
    html, body, [class*="css"], .stApp {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    
    /* Hiệu ứng Glassmorphism cho Header */
    .header-container {
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        padding: 2.5rem;
        border-radius: 16px;
        color: white;
        margin-bottom: 2rem;
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.2);
        border: 1px solid rgba(255, 255, 255, 0.1);
        text-align: center;
    }
    
    .header-title {
        font-size: 2.5rem;
        font-weight: 800;
        margin-bottom: 0.5rem;
        background: linear-gradient(to right, #ffffff, #8ae6fb);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    
    .header-subtitle {
        font-size: 1.1rem;
        font-weight: 300;
        opacity: 0.9;
    }
    
    /* Nút bấm Premium */
    .stButton>button {
        width: 100%;
        background: linear-gradient(135deg, #1d976c 0%, #93f9b9 100%);
        color: #0d3b2c !important;
        font-weight: 700;
        border: none;
        border-radius: 8px;
        padding: 0.75rem;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(29, 151, 108, 0.2);
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(29, 151, 108, 0.4);
    }
    
    /* Chỉ báo Metric */
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border-top: 5px solid #007bff;
        text-align: center;
    }
    
    /* Category styles */
    .badge-vip {
        background-color: #28a745;
        color: white;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: bold;
    }
    .badge-potential {
        background-color: #ffa500;
        color: white;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: bold;
    }
    .badge-trash {
        background-color: #dc3545;
        color: white;
        padding: 4px 10px;
        border-radius: 4px;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

# --- KHU VỰC CÁC HÀM TRỢ GIÚP (HELPER FUNCTIONS) ---

def load_scoring_skill():
    """Đọc file md chứa tiêu chí chấm điểm khách hàng"""
    try:
        with open("lead_scoring_skill.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Lỗi: Không tìm thấy file `lead_scoring_skill.md` trong thư mục."

def load_data_from_url(sheet_url):
    """Đọc dữ liệu từ link Google Sheet công khai (không cần API Key Google)"""
    try:
        # Nếu là link chỉnh sửa thông thường, chuyển về dạng tải CSV
        if "/edit" in sheet_url:
            csv_url = sheet_url.split("/edit")[0] + "/export?format=csv"
        # Nếu là link xuất bản web (Publish to web)
        elif "/pubhtml" in sheet_url:
            csv_url = sheet_url.split("/pubhtml")[0] + "/pub?output=csv"
        else:
            csv_url = sheet_url
        return pd.read_csv(csv_url)
    except Exception as e:
        raise ValueError(
            f"Không thể đọc Google Sheet. Vui lòng kiểm tra lại đường dẫn.\n"
            f"Hãy đảm bảo Sheet đã được chỉnh chia sẻ công khai ở chế độ 'Người có liên kết có thể xem' (Anyone with link can view).\n"
            f"Chi tiết lỗi: {e}"
        )

def keyword_scoring(description):
    """Đánh giá nhanh bằng từ khóa (Rule-based) - Tiết kiệm chi phí, dễ hiểu"""
    score = 0
    reasons = []
    description = str(description).lower()
    
    # Từ khóa cộng điểm (VIP)
    vip_keywords = {
        "20 tỷ": "Ngân sách lớn (>= 20 tỷ)",
        "tài chính mạnh": "Tài chính mạnh",
        "không thành vấn đề": "Ngân sách linh hoạt",
        "biệt thự": "Loại hình cao cấp (Biệt thự)",
        "penthouse": "Loại hình cao cấp (Penthouse)",
        "shophouse": "Loại hình cao cấp (Shophouse)",
        "đất công nghiệp": "Quỹ đất công nghiệp",
        "văn phòng": "Diện tích văn phòng lớn",
        "quận 1": "Vị trí đắc địa (Quận 1)",
        "ven sông": "Vị trí ven sông",
        "vinhomes": "Vị trí đắc địa (Vinhomes)",
        "phú mỹ hưng": "Vị trí đắc địa (Phú Mỹ Hưng)",
        "chủ doanh nghiệp": "Đối tượng khách hàng VIP",
        "nhà đầu tư": "Nhà đầu tư chuyên nghiệp",
        "mua sỉ": "Mua sỉ/số lượng lớn",
        "pháp lý chuẩn": "Yêu cầu pháp lý minh bạch",
        "sổ hồng": "Có sổ hồng riêng",
        "đàm phán": "Thiện chí gặp trực tiếp chủ đầu tư"
    }
    
    # Từ khóa trừ điểm (Trash)
    trash_keywords = {
        "nhầm số": "Nhầm số/Dữ liệu cũ",
        "không có nhu cầu": "Không có nhu cầu thực",
        "dữ liệu cũ": "Dữ liệu cũ",
        "hỏi giá cho vui": "Không thiện chí",
        "chưa có ý định mua": "Chưa có ý định mua",
        "bảo hiểm": "Spam/Quảng cáo bảo hiểm",
        "vay vốn": "Spam/Quảng cáo vay vốn",
        "thuê bao": "Không liên lạc được (Thuê bao)",
        "không bắt máy": "Không liên lạc được",
        "không phản hồi": "Không phản hồi liên hệ",
        "yêu cầu phi thực tế": "Yêu cầu phi thực tế",
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
    
    # Phân loại dựa trên điểm số
    category = "VIP" if score >= 50 else "Trash" if score <= -50 else "Potential"
    reasoning = "Tìm thấy từ khóa: " + ", ".join(reasons) if reasons else "Nhu cầu cơ bản / Cần tư vấn thêm"
    
    return {"score": score, "category": category, "reasoning": reasoning}

def score_lead_with_ai(model, lead_row):
    """Gửi một dòng khách hàng lên Gemini để phân loại và chấm điểm"""
    # Chuyển dòng dữ liệu thành JSON để AI dễ đọc cấu trúc
    lead_json = lead_row.to_json(force_ascii=False)
    
    prompt = (
        f"Hãy đánh giá khách hàng dưới đây và trả về một đối tượng JSON chính xác theo cấu trúc quy định.\n"
        f"Chỉ trả về chuỗi JSON thô, không viết thêm giải thích gì ngoài JSON.\n"
        f"Thông tin khách hàng:\n{lead_json}"
    )
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Bóc tách JSON nếu AI trả về kèm ký hiệu ```json ... ```
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        return json.loads(text)
    except Exception as e:
        return {
            "score": 0,
            "category": "Potential",
            "reasoning": f"Lỗi gọi AI: {str(e)}"
        }

# --- GIAO DIỆN CHÍNH (MAIN UI) ---

# Header hoành tráng
st.markdown("""
    <div class="header-container">
        <div class="header-title">🏡 Real Estate Lead Scoring AI</div>
        <div class="header-subtitle">Hệ thống phân loại & chấm điểm khách hàng tiềm năng tối giản phục vụ giảng dạy</div>
    </div>
""", unsafe_allow_html=True)

# Cấu hình sidebar (Cài đặt hệ thống)
st.sidebar.title("⚙️ Cấu hình hệ thống")
api_key_input = st.sidebar.text_input(
    "Gemini API Key",
    type="password",
    value=os.getenv("GEMINI_API_KEY", ""),
    help="Điền API Key của bạn để sử dụng chế độ chấm điểm AI."
)

st.sidebar.divider()
st.sidebar.markdown("""
### 💡 Hướng dẫn cho Học viên:
1. **Chế độ Từ khóa (Rule-based)**: Không tốn chi phí, chạy lập tức, nhận diện từ khóa tĩnh.
2. **Chế độ AI (Gemini)**: Cần điền API Key. AI sẽ tự động phân tích ngữ cảnh, sắc thái nhu cầu của khách hàng để chấm điểm thông minh hơn.
3. **Google Sheet**: Chỉ cần thiết lập quyền chia sẻ cho link là "Bất kỳ ai có liên kết đều xem được" là có thể tải vào app.
""")

# Hiển thị tiêu chí chấm điểm hiện tại (Đọc từ file markdown)
with st.sidebar.expander("📄 Xem bộ tiêu chí chấm điểm (lead_scoring_skill.md)"):
    st.markdown(load_scoring_skill())

# Khởi tạo các tabs chính
tab_data, tab_scoring = st.tabs(["📊 Bước 1: Nhập dữ liệu khách hàng", "🚀 Bước 2: Chấm điểm & Phân loại"])

# --- TAB 1: NHẬP DỮ LIỆU ---
with tab_data:
    st.subheader("Nhập danh sách khách hàng cần đánh giá")
    
    source_option = st.radio(
        "Chọn phương thức nạp dữ liệu:",
        ["Google Sheet Link công khai", "Tải tệp tin (CSV / Excel) từ máy tính"],
        horizontal=True
    )
    
    df_leads = None
    
    if source_option == "Google Sheet Link công khai":
        sheet_url = st.text_input(
            "Đường dẫn Google Sheet:",
            value="https://docs.google.com/spreadsheets/d/1PtYHhTapnRp8bOVYCxkAaEb37G_7iva99xnmoO-lvG0/edit?usp=sharing"
        )
        if st.button("📥 Tải dữ liệu từ Google Sheet"):
            with st.spinner("Đang kết nối và tải dữ liệu..."):
                try:
                    df_leads = load_data_from_url(sheet_url)
                    st.session_state['raw_data'] = df_leads
                    st.success(f"Tải thành công {len(df_leads)} dòng dữ liệu từ Google Sheet!")
                except Exception as e:
                    st.error(str(e))
    else:
        uploaded_file = st.file_uploader("Chọn file dữ liệu khách hàng (.csv, .xlsx):", type=["csv", "xlsx"])
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df_leads = pd.read_csv(uploaded_file)
                else:
                    df_leads = pd.read_excel(uploaded_file)
                st.session_state['raw_data'] = df_leads
                st.success(f"Tải thành công {len(df_leads)} dòng dữ liệu từ file upload!")
            except Exception as e:
                st.error(f"Lỗi khi đọc file: {e}")

    # Hiển thị bảng dữ liệu gốc nếu có
    if 'raw_data' in st.session_state:
        st.write("### Bản xem trước dữ liệu gốc")
        st.dataframe(st.session_state['raw_data'], use_container_width=True)

# --- TAB 2: CHẤM ĐIỂM & KẾT QUẢ ---
with tab_scoring:
    if 'raw_data' not in st.session_state:
        st.info("Vui lòng nạp dữ liệu khách hàng ở Bước 1 trước.")
    else:
        st.subheader("Bắt đầu chấm điểm khách hàng")
        
        # Lựa chọn phương pháp chấm điểm
        scoring_mode = st.radio(
            "Phương pháp chấm điểm:",
            ["Rule-based (Từ khóa tĩnh)", "AI-based (Sử dụng Gemini 1.5 Flash)"],
            horizontal=True
        )
        
        run_scoring_btn = st.button("🚀 Thực hiện chấm điểm & phân loại")
        
        if run_scoring_btn:
            df_to_score = st.session_state['raw_data'].copy()
            results = []
            
            # Khởi tạo mô hình AI nếu chọn chế độ AI
            model = None
            if scoring_mode == "AI-based (Sử dụng Gemini 1.5 Flash)":
                api_key = api_key_input or os.getenv("GEMINI_API_KEY", "")
                if not api_key:
                    st.error("❌ Vui lòng nhập Gemini API Key ở Sidebar hoặc cấu hình file .env để chạy chế độ AI.")
                    st.stop()
                
                # Cấu hình thư viện Gemini
                genai.configure(api_key=api_key)
                skill_prompt = load_scoring_skill()
                
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=(
                        f"Bạn là trợ lý chấm điểm khách hàng tiềm năng cho dự án Bất Động Sản chuyên nghiệp.\n"
                        f"Hãy chấm điểm dựa vào các tiêu chí được định nghĩa dưới đây:\n\n{skill_prompt}"
                    )
                )
            
            # Tiến hành xử lý từng dòng dữ liệu
            progress_bar = st.progress(0)
            status_text = st.empty()
            total_rows = len(df_to_score)
            
            for index, row in df_to_score.iterrows():
                # Hiển thị trạng thái đang xử lý
                ten_khach = row.get('ten_khach', 'Khách hàng')
                status_text.text(f"Đang phân tích: {ten_khach} ({index + 1}/{total_rows})")
                
                if model:
                    # Chấm điểm bằng AI
                    score_res = score_lead_with_ai(model, row)
                else:
                    # Chấm điểm bằng từ khóa
                    score_res = keyword_scoring(row.get('nhu_cau_mo_ta', ''))
                
                # Tạo bản ghi kết quả hoàn chỉnh
                record = row.to_dict()
                record['Score'] = int(score_res.get('score', 0))
                record['Category'] = score_res.get('category', 'Potential')
                record['Reasoning'] = score_res.get('reasoning', '')
                results.append(record)
                
                # Cập nhật thanh tiến trình
                progress_bar.progress((index + 1) / total_rows)
            
            status_text.success("🎉 Hoàn thành chấm điểm thành công!")
            st.session_state['scored_data'] = pd.DataFrame(results)
            
        # Hiển thị kết quả sau khi chấm điểm xong
        if 'scored_data' in st.session_state:
            df_result = st.session_state['scored_data']
            
            # --- KHU VỰC THỐNG KÊ (METRICS) ---
            st.write("### Báo cáo thống kê nhanh")
            col_vip, col_pot, col_trash, col_total = st.columns(4)
            
            vip_count = len(df_result[df_result['Category'] == 'VIP'])
            pot_count = len(df_result[df_result['Category'] == 'Potential'])
            trash_count = len(df_result[df_result['Category'] == 'Trash'])
            
            with col_vip:
                st.markdown(f"""
                <div class="metric-card" style="border-top-color: #28a745;">
                    <h4 style="color: #28a745; margin:0;">🌟 Khách VIP</h4>
                    <h2 style="margin: 5px 0;">{vip_count}</h2>
                    <span style="font-size:0.85rem; color:#666;">(Điểm >= 50)</span>
                </div>
                """, unsafe_allow_html=True)
                
            with col_pot:
                st.markdown(f"""
                <div class="metric-card" style="border-top-color: #ffa500;">
                    <h4 style="color: #ffa500; margin:0;">⚖️ Tiềm năng</h4>
                    <h2 style="margin: 5px 0;">{pot_count}</h2>
                    <span style="font-size:0.85rem; color:#666;">(0 <= Điểm < 50)</span>
                </div>
                """, unsafe_allow_html=True)
                
            with col_trash:
                st.markdown(f"""
                <div class="metric-card" style="border-top-color: #dc3545;">
                    <h4 style="color: #dc3545; margin:0;">🗑️ Khách rác</h4>
                    <h2 style="margin: 5px 0;">{trash_count}</h2>
                    <span style="font-size:0.85rem; color:#666;">(Điểm < 0)</span>
                </div>
                """, unsafe_allow_html=True)
                
            with col_total:
                st.markdown(f"""
                <div class="metric-card" style="border-top-color: #6c757d;">
                    <h4 style="color: #6c757d; margin:0;">📋 Tổng cộng</h4>
                    <h2 style="margin: 5px 0;">{len(df_result)}</h2>
                    <span style="font-size:0.85rem; color:#666;">Khách hàng đã quét</span>
                </div>
                """, unsafe_allow_html=True)
            
            st.write("---")
            
            # --- HIỂN THỊ BẢNG KẾT QUẢ ---
            st.write("### Chi tiết danh sách kết quả chấm điểm")
            
            # Tô màu cho cột Category trong bảng để tăng trải nghiệm người dùng
            def highlight_category(val):
                if val == 'VIP':
                    return 'background-color: #d4edda; color: #155724; font-weight: bold;'
                elif val == 'Trash':
                    return 'background-color: #f8d7da; color: #721c24; font-weight: bold;'
                else:
                    return 'background-color: #fff3cd; color: #856404; font-weight: bold;'
            
            styled_df = df_result.style.map(highlight_category, subset=['Category'])
            st.dataframe(styled_df, use_container_width=True)
            
            # --- XUẤT FILE EXCEL ---
            # Ghi dữ liệu ra một file Excel dạng byte in-memory để tải xuống trực tiếp
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_result.to_excel(writer, index=False, sheet_name='Leads Scored')
            excel_bytes = output.getvalue()
            
            st.write("")
            st.download_button(
                label="📥 Tải xuống kết quả phân loại (Excel .xlsx)",
                data=excel_bytes,
                file_name="leads_scored_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
