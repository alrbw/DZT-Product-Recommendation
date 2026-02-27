# ==========================================
# CẤU HÌNH API KEY TỪ STREAMLIT SECRETS
# ==========================================
import streamlit as st
import pandas as pd  # <--- ĐẢM BẢO CÓ DÒNG NÀY
import openai
from openai import OpenAI
import urllib.parse
import textwrap
import re

# Lấy key từ hệ thống quản lý bí mật của Streamlit
if "OPENAI_API_KEY" in st.secrets:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
else:
    OPENAI_API_KEY = "" # Hoặc thông báo lỗi
# ==========================================
# ==========================================

# Thiết lập giao diện rộng và tên Tab
st.set_page_config(page_title="DZT-Search: Product Recommendation", page_icon="🚀", layout="wide")

# Khởi tạo bộ nhớ tạm (Session State) để giữ kết quả AI của TỪNG SẢN PHẨM
if 'ai_results' not in st.session_state:
    st.session_state['ai_results'] = {}

def format_currency(value):
    return f"${value:,.2f}"

# --- LOGIC TẠO LINK VÀ LỌC TỪ KHÓA TÌM KIẾM ---
def create_search_links(query):
    # Lọc bỏ các ký tự có thể làm gãy link
    clean_query = query.replace('"', '').replace("'", "").replace("|", "").strip()
    encoded_query = urllib.parse.quote_plus(clean_query)
    
    amz_url = f"https://www.amazon.com/s?k={encoded_query}"
    ets_url = f"https://www.etsy.com/search?q={encoded_query}"
    
    # SỬA LỖI Ở ĐÂY: Dùng thẻ <br> để link rớt dòng gọn gàng, KHÔNG dùng dấu | tránh vỡ Markdown Table
    return f"[🛒 AMZ]({amz_url})<br>[🛍️ ETS]({ets_url})"

def clean_niche(niche_raw):
    cleaned = re.sub(r'\([^)]*\)', '', str(niche_raw)).strip().lower()
    return cleaned

def get_market_link_b2(prod_name, niche_raw=""):
    if not niche_raw:
        return create_search_links(prod_name)
        
    niche_clean = clean_niche(niche_raw)
    
    if not niche_clean or niche_clean == '0' or niche_clean == 'nan' or niche_clean == 'none':
        return create_search_links(prod_name)
        
    if niche_clean in ['self gift', 'sgt', 'myself']:
        query = f"{prod_name} for myself"
        return create_search_links(query)

    events = ['christmas', 'halloween', 'birthday', 'memorial', 'graduation', 
              'retirement', 'wedding', 'anniversary', 'valentine', 'summer', 'back to school', 'newborn', 'baptism', 'thanksgiving']
              
    is_event = any(e in niche_clean for e in events)
    
    if is_event:
        query = f"{niche_clean} gift {prod_name}"
    else:
        query = f"{prod_name} gift for {niche_clean}"
        
    return create_search_links(query)

# --- HÀM ĐỌC FILE CSV CHỐNG VỠ CẤU TRÚC ---
def load_data(file):
    try:
        file.seek(0)
        return pd.read_csv(file, encoding='utf-8')
    except UnicodeDecodeError:
        try:
            file.seek(0)
            return pd.read_csv(file, encoding='latin1')
        except Exception:
            file.seek(0)
            return pd.read_csv(file, encoding='latin1', engine='python', on_bad_lines='skip')
    except Exception:
        file.seek(0)
        return pd.read_csv(file, engine='python', on_bad_lines='skip')

# --- LOGIC TÍNH TOÁN DỮ LIỆU ĐÃ ĐƯỢC CHUẨN HÓA LẠI ---
def get_analytics(sales_df, target_product):
    try:
        # Lấy dòng thông tin của SP mục tiêu
        target_row = sales_df[sales_df['Product Base'] == target_product].iloc[0]
        niche_col = 'NICHE-DETAILS' if 'NICHE-DETAILS' in sales_df.columns else 'NICHE'
        
        # 1. TÌM NICHE WIN CỦA RIÊNG SẢN PHẨM MỤC TIÊU
        target_df = sales_df[sales_df['Product Base'] == target_product].copy()
        target_niche_perf = target_df.groupby(niche_col)['SUM of Total Revenue'].sum().sort_values(ascending=False).reset_index()

        # 2. TÌM CÁC SP CÙNG LINE (Cùng Product Line, không lấy chéo Website Categories)
        same_line_df = sales_df[sales_df['Product Line'] == target_row['Product Line']].copy()
        
        # Thống kê SP cùng Line
        same_line_perf = same_line_df.groupby('Product Base')['SUM of Total Revenue'].sum().sort_values(ascending=False).reset_index()
        
        # 3. TÌM NICHE WIN CỦA CẢ LINE ĐÓ
        line_niche_perf = same_line_df.groupby(niche_col)['SUM of Total Revenue'].sum().sort_values(ascending=False).reset_index()
        
        return same_line_perf.head(15), line_niche_perf.head(10), target_niche_perf.head(10)
    except Exception: 
        return None, None, None

def ask_ai_final_v20(target_info, catalog_set, top_5_niches, catalog_context=""):
    if not OPENAI_API_KEY or "DÁN_API_KEY" in OPENAI_API_KEY:
        return "⚠️ Lỗi: Chưa cấu hình API Key. Vui lòng cập nhật API Key vào mã nguồn."
    
    client = OpenAI(api_key=OPENAI_API_KEY, timeout=120.0, max_retries=3)
    niches_str = ", ".join(map(str, top_5_niches))
    
    catalog_list = [str(x) for x in catalog_set if str(x).lower() != 'nan']
    if len(catalog_list) > 150:
        catalog_str = ", ".join(catalog_list[:150]) + f" ... (và {len(catalog_list) - 150} sản phẩm khác)"
    else:
        catalog_str = ", ".join(catalog_list)
    
    prompt = f"""
Bạn là chuyên gia R&D POD cao cấp. 
Mục tiêu phân tích: {target_info['Product Base']}

DANH SÁCH SẢN PHẨM ĐÃ CÓ TRONG CATALOG (TUYỆT ĐỐI CẤM ĐỀ XUẤT LẠI TRÙNG TÊN): 
{catalog_str}

{catalog_context}

NHIỆM VỤ:
1. BẢNG 1 (Market Trends): Đề xuất 5 sản phẩm trending Amazon/Etsy tương đồng CÔNG NĂNG & VẬT LIỆU với sản phẩm mục tiêu.
   - Trình bày dưới dạng BẢNG MARKDOWN bao gồm các cột: Product Name | Sales/Favs | Keywords | Note | Ref Link
   - Sales/Favs: Đưa số liệu thực tế (VD: 2,400+ sold/mo).
   - Keywords: 3-4 từ khóa ngách dài. (Ngăn cách bằng dấu phẩy).
   - Note: Giải thích sâu về kỹ thuật (vùng in/khắc, combo quà tặng).
   - Ref Link: Ở TẤT CẢ CÁC DÒNG SẢN PHẨM, BẮT BUỘC ghi đúng chữ 'INSERT_LINK_HERE'

2. BẢNG 2 (Scale): Đề xuất 5 sản phẩm MỚI (TUYỆT ĐỐI KHÔNG CÓ TRONG CATALOG) tương ứng cho 5 Niche win sau: {niches_str}.
   - Trình bày dưới dạng BẢNG MARKDOWN bao gồm các cột: Niche | Product Name | Features and Design | Ref Link
   - Cột Niche: BẮT BUỘC ghi lại chính xác mã Niche được cung cấp (VD: COUPLE (COU), DAD (DAD)...).
   - Sản phẩm phải có tính khả thi, cùng kỹ thuật sản xuất (in/khắc/vật liệu). Bạn ĐƯỢC TOÀN QUYỀN SÁNG TẠO kiểu dáng, tính năng mới.
   - Ref Link: Ở TẤT CẢ CÁC DÒNG SẢN PHẨM, BẮT BUỘC ghi đúng chữ 'INSERT_LINK_HERE'

YÊU CẦU ĐỊNH DẠNG TỐI QUAN TRỌNG: 
- CHỈ XUẤT VĂN BẢN CHỨA BẢNG MARKDOWN CHUẨN.
- TUYỆT ĐỐI KHÔNG bọc nội dung trong thẻ ```markdown hay ```.
- KHÔNG DÙNG DẤU CÁCH (SPACE) HOẶC TAB để lùi đầu dòng. Tất cả văn bản phải viết sát lề trái.
- KHÔNG giải thích luyên thuyên thừa, đi thẳng vào vẽ 2 bảng.
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o", 
            messages=[{"role": "user", "content": prompt.strip()}],
            temperature=0.7 
        )
        return response.choices[0].message.content
    except openai.APIConnectionError:
        return "⚠️ **LỖI MẠNG (API Connection Error):** Không thể kết nối tới máy chủ OpenAI. Hãy kiểm tra lại kết nối mạng hoặc tắt VPN."
    except openai.APITimeoutError:
        return "⚠️ **LỖI THỜI GIAN CHỜ (Timeout):** Máy chủ OpenAI phản hồi quá lâu. Vui lòng thử lại."
    except openai.AuthenticationError:
        return "⚠️ **LỖI API KEY:** API Key của bạn không chính xác hoặc đã bị xóa."
    except Exception as e:
        return f"⚠️ **LỖI KHÁC:** {str(e)}"


# --- HÀM XỬ LÝ TEXT AI TRẢ VỀ ĐỂ VẼ BẢNG ---
def display_ai_result(ai_raw):
    if ai_raw.startswith("⚠️"):
        st.warning(ai_raw)
        return

    ai_raw = ai_raw.replace("```markdown", "").replace("```md", "").replace("```html", "").replace("```", "")
    lines = ai_raw.split('\n')
    final_table = []
    current_table = ""
    
    for line in lines:
        clean_line = line.strip()
        if not clean_line:
            final_table.append(clean_line)
            continue
        
        if "BẢNG 1" in clean_line.upper() or "MARKET TRENDS" in clean_line.upper(): 
            current_table = "B1"
            clean_line = "### 🌍 " + clean_line.replace("#", "").strip()
        elif "BẢNG 2" in clean_line.upper() or "SCALE" in clean_line.upper(): 
            current_table = "B2"
            clean_line = "### 💡 " + clean_line.replace("#", "").strip()
        
        if '|' in clean_line and 'INSERT_LINK_HERE' in clean_line:
            parts = [p.strip() for p in clean_line.split('|')]
            offset = 1 if len(parts) > 0 and parts[0] == '' else 0
            
            try:
                if current_table == "B1" and len(parts) >= 3 + offset:
                    keywords = parts[offset + 2].replace('**','')
                    p_name = parts[offset].replace('**','')
                    primary_keyword = keywords.split(',')[0].strip() if keywords else p_name
                    
                    if primary_keyword.lower() == 'keywords' or p_name.lower() == 'product name':
                        clean_line = clean_line.replace('INSERT_LINK_HERE', 'Ref Link')
                    else:
                        clean_line = clean_line.replace('INSERT_LINK_HERE', create_search_links(primary_keyword))
                        
                elif current_table == "B2" and len(parts) >= 2 + offset:
                    raw_niche = parts[offset].replace('**','')
                    p_name = parts[offset + 1].replace('**','')
                    
                    if raw_niche.lower() == 'niche':
                        clean_line = clean_line.replace('INSERT_LINK_HERE', 'Ref Link')
                    else:
                        clean_line = clean_line.replace('INSERT_LINK_HERE', get_market_link_b2(p_name, raw_niche))
                else:
                    p_name = parts[offset].replace('**','')
                    if p_name.lower() in ['product name', 'niche']:
                        clean_line = clean_line.replace('INSERT_LINK_HERE', 'Ref Link')
                    else:
                        clean_line = clean_line.replace('INSERT_LINK_HERE', create_search_links(p_name))
            except Exception: 
                pass
        
        final_table.append(clean_line)
        
    # Thêm unsafe_allow_html=True để hiển thị được thẻ <br> trong bảng Markdown
    st.markdown("\n".join(final_table), unsafe_allow_html=True)


# ==========================================
# GIAO DIỆN CHÍNH
# ==========================================
st.title("🚀 DZT-Search: Product Recommendation")

with st.sidebar:
    st.header("📂 Data Sources")
    sales_file = st.file_uploader("1. Sales History (CSV)", type=['csv'])
    catalog_file = st.file_uploader("2. Your Catalog (CSV)", type=['csv'])
    
    st.markdown("---")
    if st.button("🗑️ Xóa toàn bộ bộ nhớ AI", use_container_width=True):
        st.session_state['ai_results'] = {}
        st.rerun()

if sales_file:
    df_sales = load_data(sales_file)

    if not df_sales.empty:
        if 'SUM of Total Revenue' in df_sales.columns and df_sales['SUM of Total Revenue'].dtype == object:
            df_sales['SUM of Total Revenue'] = df_sales['SUM of Total Revenue'].replace(r'[\$,\s]', '', regex=True).astype(float)
        
        catalog_set = set()
        df_cat = pd.DataFrame()

        if catalog_file:
            df_cat = load_data(catalog_file)
            if not df_cat.empty:
                prod_col = 'Product Base' if 'Product Base' in df_cat.columns else df_cat.columns[0]
                catalog_set = set(df_cat[prod_col].dropna().astype(str).unique())

        # Ô TÌM KIẾM DẠNG GÕ (TYPE TO SEARCH)
        product_options = sorted(df_sales['Product Base'].dropna().unique().tolist())
        search_query = st.selectbox(
            label="🔍 Gõ hoặc chọn sản phẩm mục tiêu (Type to search):", 
            options=product_options,
            index=None, 
            placeholder="Ví dụ: Leather Wallet..."
        )

        if search_query:
            same_line, line_niches, target_niches = get_analytics(df_sales, search_query)
            
            if same_line is not None and not same_line.empty:
                # GIAO DIỆN 3 CỘT ĐẸP MẮT
                st.markdown("---")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.subheader(f"🎯 Niche Win của [{search_query[:15]}...]")
                    st.caption("Ngách bán tốt CỦA RIÊNG SẢN PHẨM NÀY")
                    df_tn_display = target_niches.copy()
                    df_tn_display['SUM of Total Revenue'] = df_tn_display['SUM of Total Revenue'].apply(format_currency)
                    st.dataframe(df_tn_display, use_container_width=True, hide_index=True)
                
                with col2:
                    st.subheader("📈 Trending Niches")
                    st.caption("Ngách phổ biến của TOÀN BỘ PRODUCT LINE")
                    df_ln_display = line_niches.copy()
                    df_ln_display['SUM of Total Revenue'] = df_ln_display['SUM of Total Revenue'].apply(format_currency)
                    st.dataframe(df_ln_display, use_container_width=True, hide_index=True)

                with col3:
                    st.subheader("📦 Sản Phẩm Cùng Line")
                    st.caption("Các sản phẩm khác bán chạy trong Line")
                    df_sl_display = same_line.copy()
                    df_sl_display['SUM of Total Revenue'] = df_sl_display['SUM of Total Revenue'].apply(format_currency)
                    st.dataframe(df_sl_display, use_container_width=True, hide_index=True)

                st.divider()

                # KIỂM TRA BỘ NHỚ ĐỆM ĐỂ HIỂN THỊ NÚT BẤM
                has_result = search_query in st.session_state['ai_results']
                btn_label = f"🔄 Renew AI Research cho {search_query}" if has_result else f"✨ Thực hiện Research Market (AI R&D)"
                btn_type = "secondary" if has_result else "primary"
                
                if st.button(btn_label, type=btn_type, use_container_width=True):
                    with st.spinner("Đang phân tích thị trường & kết nối OpenAI... Vui lòng chờ..."):
                        target_info = df_sales[df_sales['Product Base'] == search_query].iloc[0]
                        n_col = 'NICHE-DETAILS' if 'NICHE-DETAILS' in line_niches.columns else line_niches.columns[0]
                        
                        # Sử dụng Niche chung của toàn bộ Line để AI có không gian scale rộng hơn
                        top_5 = line_niches.head(5)[n_col].tolist()
                        
                        catalog_context = ""
                        if not df_cat.empty and 'Product Details' in df_cat.columns:
                            details_sample = df_cat.dropna(subset=['Product Details'])
                            details_sample = details_sample[details_sample['Product Details'].astype(str).str.strip() != '']
                            
                            if not details_sample.empty:
                                info_list = []
                                prod_col_cat = 'Product Base' if 'Product Base' in df_cat.columns else df_cat.columns[0]
                                target_details = details_sample[details_sample[prod_col_cat] == search_query]
                                if not target_details.empty:
                                    sample_df = pd.concat([target_details.head(1), details_sample.sample(min(2, len(details_sample)))])
                                else:
                                    sample_df = details_sample.sample(min(3, len(details_sample)))
                                    
                                for _, row in sample_df.iterrows():
                                    detail_text = textwrap.shorten(str(row['Product Details']).replace('\n', ' '), width=200, placeholder="...")
                                    info_list.append(f"- {row[prod_col_cat]}: {detail_text}")
                                
                                if info_list:
                                    catalog_context = (
                                        "\n\n--- [THÔNG TIN THAM KHẢO VỀ SẢN PHẨM CỦA SHOP (KHÔNG BẮT BUỘC)] ---\n"
                                        "⚠️ LƯU Ý: Đừng sao chép y hệt. Hãy tự do đề xuất những đặc điểm mới:\n"
                                        + "\n".join(info_list) + "\n\n"
                                    )

                        # GỌI AI
                        ai_raw = ask_ai_final_v20(target_info, catalog_set, top_5, catalog_context)
                        
                        # LƯU VÀO SESSION VÀ HIỂN THỊ
                        st.session_state['ai_results'][search_query] = ai_raw

                # HIỂN THỊ KẾT QUẢ AI ĐÃ LƯU
                if search_query in st.session_state['ai_results']:
                    st.success(f"✅ Đang hiển thị kết quả phân tích AI đã lưu trữ cho: **{search_query}**")
                    with st.container():
                        display_ai_result(st.session_state['ai_results'][search_query])

            else:
                st.warning("Không tìm thấy dữ liệu liên quan đến sản phẩm này để đề xuất.")
else:

    st.info("👋 Vui lòng upload dữ liệu Sales History (và Catalog nếu có) ở thanh công cụ bên trái để bắt đầu.")
