"""
Facebook Ads Domain Search - Streamlit App
Fixed version with working save functionality and real-time table creation
"""

import streamlit as st
import json
import sqlite3
import os
from datetime import datetime, timedelta, timezone, date
from apify_client import ApifyClient
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote_plus
import time

# =============================================================================
# DATABASE FUNCTIONS
# =============================================================================

def init_database():
    """Initialize SQLite database"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    
    # Create tables table to track different collections
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ad_tables (
            table_name TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def create_ads_table(table_name: str, description: str = ""):
    """Create a new table for saving ads"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    
    # Sanitize table name - make it unique with timestamp if needed
    base_name = "ads_" + "".join(c for c in table_name if c.isalnum() or c in ('_',)).lower()
    safe_table_name = base_name
    
    # Check if table already exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (safe_table_name,))
    if cursor.fetchone():
        # Add timestamp to make unique
        safe_table_name = f"{base_name}_{int(time.time())}"
    
    # Create the ads table with all fields
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {safe_table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_archive_id TEXT UNIQUE,
            page_name TEXT,
            page_id TEXT,
            categories TEXT,
            start_date TEXT,
            end_date TEXT,
            is_active BOOLEAN,
            cta_text TEXT,
            cta_type TEXT,
            link_url TEXT,
            display_url TEXT,
            website_url TEXT,
            original_image_url TEXT,
            video_url TEXT,
            collation_count INTEGER,
            collation_id TEXT,
            entity_type TEXT,
            page_entity_type TEXT,
            page_profile_picture_url TEXT,
            page_profile_uri TEXT,
            state_media_run_label TEXT,
            total_active_time TEXT,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            notes TEXT
        )
    ''')
    
    # Add to tables registry
    cursor.execute('''
        INSERT OR REPLACE INTO ad_tables (table_name, description, created_at)
        VALUES (?, ?, datetime('now'))
    ''', (safe_table_name, description))
    
    conn.commit()
    conn.close()
    
    return safe_table_name

def get_available_tables():
    """Get list of available tables"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    
    # First check if ad_tables exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ad_tables'")
    if not cursor.fetchone():
        conn.close()
        return []
    
    cursor.execute('SELECT table_name, description, created_at FROM ad_tables ORDER BY created_at DESC')
    tables = cursor.fetchall()
    
    conn.close()
    return tables

def save_ad_to_table(table_name: str, ad_data: dict, notes: str = ""):
    """Save an ad to specified table"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    
    try:
        # Check if ad already exists
        cursor.execute(f'''
            SELECT id FROM {table_name} WHERE ad_archive_id = ?
        ''', (ad_data.get("ad_archive_id"),))
        
        if cursor.fetchone():
            conn.close()
            return False, "Ad already exists in this collection"
        
        # Insert the ad
        cursor.execute(f'''
            INSERT INTO {table_name} (
                ad_archive_id, page_name, page_id, categories, start_date, end_date,
                is_active, cta_text, cta_type, link_url, display_url, website_url,
                original_image_url, video_url, collation_count, collation_id,
                entity_type, page_entity_type, page_profile_picture_url,
                page_profile_uri, state_media_run_label, total_active_time, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            ad_data.get("ad_archive_id"),
            ad_data.get("page_name"),
            ad_data.get("page_id"),
            ad_data.get("categories"),
            ad_data.get("start_date"),
            ad_data.get("end_date"),
            ad_data.get("is_active"),
            ad_data.get("cta_text"),
            ad_data.get("cta_type"),
            ad_data.get("link_url"),
            ad_data.get("display_url"),
            ad_data.get("website_url"),
            ad_data.get("original_image_url"),
            ad_data.get("video_url"),
            ad_data.get("collation_count"),
            ad_data.get("collation_id"),
            ad_data.get("entity_type"),
            ad_data.get("page_entity_type"),
            ad_data.get("page_profile_picture_url"),
            ad_data.get("page_profile_uri"),
            ad_data.get("state_media_run_label"),
            ad_data.get("total_active_time"),
            notes
        ))
        
        conn.commit()
        conn.close()
        return True, "Ad saved successfully!"
    except Exception as e:
        conn.close()
        return False, f"Error saving ad: {str(e)}"

def get_saved_ads(table_name: str):
    """Get all saved ads from a table"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(f'''
            SELECT * FROM {table_name} ORDER BY saved_at DESC
        ''')
        
        columns = [description[0] for description in cursor.description]
        ads = []
        
        for row in cursor.fetchall():
            ad_dict = dict(zip(columns, row))
            ads.append(ad_dict)
        
        conn.close()
        return ads
    except Exception as e:
        conn.close()
        print(f"Error getting saved ads: {e}")
        return []

def delete_saved_ad(table_name: str, ad_id: int):
    """Delete a saved ad"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    
    cursor.execute(f'DELETE FROM {table_name} WHERE id = ?', (ad_id,))
    
    conn.commit()
    conn.close()

def delete_table(table_name: str):
    """Delete an entire table and its registry entry"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(f'DROP TABLE IF EXISTS {table_name}')
        cursor.execute('DELETE FROM ad_tables WHERE table_name = ?', (table_name,))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.close()
        print(f"Error deleting table: {e}")
        return False

# =============================================================================
# DATE FILTERING HELPER
# =============================================================================

def is_date_in_range(date_str: str, start_date: date, end_date: date) -> bool:
    """Check if date falls within selected date range"""
    if not date_str:
        return True
    
    try:
        if 'T' in date_str:
            ad_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
        else:
            ad_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        return start_date <= ad_date <= end_date
    except Exception:
        return True

# =============================================================================
# IMAGE EXTRACTION LOGIC
# =============================================================================

def _get_snapshot_dict(item: dict) -> dict:
    """Extract snapshot JSON from API response"""
    snap = item.get("snapshot")
    if isinstance(snap, str):
        try:
            snap = json.loads(snap)
        except Exception:
            snap = {}
    if not isinstance(snap, dict):
        snap = {}
    return snap

def get_original_image_url(item: dict) -> str | None:
    """Extract image URL using original code logic"""
    snap = _get_snapshot_dict(item)
    
    imgs = snap.get("images")
    if isinstance(imgs, dict):
        imgs = [imgs]
    elif not isinstance(imgs, (list, tuple)):
        imgs = []
    
    for im in imgs:
        if not isinstance(im, dict):
            continue
        for k in ("original_image_url", "original_picture_url", "original_picture", "url", "src"):
            v = im.get(k)
            if v:
                return v
    return None

def extract_selected_fields(item: dict) -> dict:
    """Extract fields using original code logic"""
    snap = _get_snapshot_dict(item)
    
    card0 = None
    cards = snap.get("cards")
    if isinstance(cards, list) and cards:
        if isinstance(cards[0], dict):
            card0 = cards[0]
    elif isinstance(cards, dict):
        card0 = cards
    
    pgcat0 = None
    page_categories = snap.get("page_categories")
    if isinstance(page_categories, list) and page_categories:
        if isinstance(page_categories[0], dict):
            pgcat0 = page_categories[0]
    elif isinstance(page_categories, dict):
        pgcat0 = page_categories
    
    link_url = snap.get("link_url")
    if not link_url and isinstance(card0, dict):
        link_url = card0.get("link_url")
    
    display_url = snap.get("caption")
    website_url = snap.get("link_url") or snap.get("website") or snap.get("url")
    
    categories = item.get("categories")
    if isinstance(categories, (list, tuple)):
        categories_disp = ", ".join(str(c) for c in categories)
    else:
        categories_disp = categories
    
    image_url = get_original_image_url(item)
    if not image_url:
        img_keys = ["imageUrl", "image_url", "thumbnailUrl", "thumbnail_url", "image"]
        for k in img_keys:
            if item.get(k):
                image_url = item[k]
                break
    
    video_url = None
    videos = snap.get("videos")
    if isinstance(videos, dict):
        videos = [videos]
    elif not isinstance(videos, (list, tuple)):
        videos = []
    
    for vid in videos:
        if not isinstance(vid, dict):
            continue
        for k in ("video_hd_url", "video_sd_url", "video_preview_url", "url", "src"):
            v = vid.get(k)
            if v:
                video_url = v
                break
        if video_url:
            break
    
    if not video_url:
        vid_keys = ["videoUrl", "video_url", "video", "video_hd_url", "video_sd_url"]
        for k in vid_keys:
            if item.get(k):
                video_url = item[k]
                break
            if snap.get(k):
                video_url = snap[k]
                break
    
    return {
        "ad_archive_id": item.get("ad_archive_id") or item.get("adId"),
        "categories": categories_disp,
        "collation_count": item.get("collation_count"),
        "collation_id": item.get("collation_id"),
        "start_date": item.get("start_date") or item.get("startDate"),
        "end_date": item.get("end_date") or item.get("endDate"),
        "entity_type": item.get("entity_type"),
        "is_active": item.get("is_active"),
        "page_id": item.get("page_id") or item.get("pageId"),
        "page_name": item.get("page_name") or item.get("pageName"),
        "cta_text": (card0.get("cta_text") if isinstance(card0, dict) else None) or snap.get("cta_text"),
        "cta_type": (card0.get("cta_type") if isinstance(card0, dict) else None) or snap.get("cta_type"),
        "link_url": link_url,
        "display_url": display_url,
        "website_url": website_url,
        "page_entity_type": (pgcat0.get("page_entity_type") if isinstance(pgcat0, dict) else None) or item.get("page_entity_type"),
        "page_profile_picture_url": item.get("page_profile_picture_url") or snap.get("page_profile_picture_url"),
        "page_profile_uri": item.get("page_profile_uri") or snap.get("page_profile_uri"),
        "state_media_run_label": item.get("state_media_run_label"),
        "total_active_time": item.get("total_active_time"),
        "original_image_url": image_url,
        "video_url": video_url,
    }

# =============================================================================
# SCRAPING FUNCTION
# =============================================================================

def run_facebook_ads_scrape(
    apify_token: str,
    domain: str,
    count: int = 10,
    country: str = "US",
    exact_phrase: bool = False,
    active_status: str = "active",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
) -> List[Dict[str, Any]]:
    """Run domain search via Apify"""
    
    if exact_phrase:
        domain_query = f'"{domain.strip()}"'
        search_type = "keyword_exact_phrase"
    else:
        domain_query = domain.strip()
        search_type = "keyword_unordered"
    
    domain_encoded = quote_plus(domain_query)
    
    url = (
        f"https://www.facebook.com/ads/library/?"
        f"active_status={active_status}&"
        f"ad_type=all&"
        f"country={country.upper()}&"
        f"is_targeted_country=false&"
        f"media_type=all&"
        f"q={domain_encoded}&"
        f"search_type={search_type}"
    )
    
    if start_date and end_date:
        url += f"&start_date[min]={start_date.strftime('%Y-%m-%d')}"
        url += f"&start_date[max]={end_date.strftime('%Y-%m-%d')}"
    
    client = ApifyClient(apify_token)
    
    run_input = {
        "urls": [{"url": url, "method": "GET"}],
        "count": int(count),
        "scrapeAdDetails": True,
        "scrapePageAds.activeStatus": active_status,
        "period": ""
    }
    
    try:
        run = client.actor("curious_coder/facebook-ads-library-scraper").call(run_input=run_input)
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            raise Exception("No dataset ID returned from Apify")
        
        items = list(client.dataset(dataset_id).iterate_items())
        
        processed_items = []
        for item in items:
            processed_item = extract_selected_fields(item)
            
            if start_date and end_date:
                start_date_str = processed_item.get("start_date")
                if start_date_str and not is_date_in_range(start_date_str, start_date, end_date):
                    continue
            
            processed_items.append(processed_item)
        
        return processed_items
        
    except Exception as e:
        st.error(f"Error running scrape: {e}")
        return []

# =============================================================================
# DISPLAY FUNCTIONS
# =============================================================================

def display_ad_card(ad, index, show_save_button=True):
    """Display ad card in modern grid layout"""
    page_name = ad.get("page_name") or "Unknown Page"
    ad_id = ad.get("ad_archive_id") or f"ad_{index}"
    is_active = ad.get("is_active")
    cta_text = ad.get("cta_text")
    start_date = ad.get("start_date")
    image_url = ad.get("original_image_url")
    video_url = ad.get("video_url")
    display_url = ad.get("display_url")
    
    with st.container():
        # Save button
        if show_save_button:
            if st.button(f"💾 Save", key=f"save_btn_{ad_id}_{index}", help="Save this ad"):
                st.session_state.save_modal_ad = ad
                st.rerun()
        
        # Display media
        if video_url:
            try:
                st.video(video_url)
            except:
                if image_url:
                    try:
                        st.image(image_url, use_container_width=True)
                    except:
                        st.info("📹 Media not available")
        elif image_url:
            try:
                st.image(image_url, use_container_width=True)
            except:
                st.info("🖼️ Image not available")
        else:
            st.info("No media available")
        
        # Card info
        st.markdown(f"**{page_name}**")
        if start_date:
            st.caption(f"📅 {start_date}")
        if is_active is not None:
            st.caption(f"{'🟢 Active' if is_active else '🔴 Inactive'}")
        if display_url:
            st.caption(f"🔗 {display_url}")
        if cta_text:
            st.info(f"CTA: {cta_text}")
        
        # Details expander
        with st.expander("View Details"):
            if ad.get('ad_archive_id'):
                fb_url = f"https://www.facebook.com/ads/library/?id={ad['ad_archive_id']}"
                st.markdown(f"[View on Facebook]({fb_url})")
            
            col1, col2 = st.columns(2)
            with col1:
                if ad.get('page_id'):
                    st.write(f"**Page ID:** {ad['page_id']}")
                if ad.get('categories'):
                    st.write(f"**Categories:** {ad['categories']}")
                if ad.get('cta_type'):
                    st.write(f"**CTA Type:** {ad['cta_type']}")
                if ad.get('website_url'):
                    st.write(f"**Website:** {ad['website_url']}")
            
            with col2:
                if ad.get('end_date'):
                    st.write(f"**End Date:** {ad['end_date']}")
                if ad.get('total_active_time'):
                    st.write(f"**Active Time:** {ad['total_active_time']}")
                if ad.get('collation_count'):
                    st.write(f"**Similar Ads:** {ad['collation_count']}")
                if ad.get('entity_type'):
                    st.write(f"**Entity Type:** {ad['entity_type']}")

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Facebook Ads Domain Search", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .main { padding: 0rem 1rem; }
    .stButton > button {
        width: 100%;
        background: #1877f2;
        color: white;
        border: none;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        font-weight: 500;
    }
    .stButton > button:hover { background: #166fe5; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)

# Initialize database
init_database()

# Initialize session state
if 'current_ads' not in st.session_state:
    st.session_state.current_ads = []
if 'save_modal_ad' not in st.session_state:
    st.session_state.save_modal_ad = None
if 'selected_table' not in st.session_state:
    st.session_state.selected_table = None

# =============================================================================
# MAIN APP
# =============================================================================

def main():
    """Main Streamlit app"""
    
    # Handle save modal
    if st.session_state.save_modal_ad:
        with st.sidebar:
            st.markdown("### 💾 Save Ad to Collection")
            st.markdown("---")
            
            ad_to_save = st.session_state.save_modal_ad
            st.info(f"Saving: {ad_to_save.get('page_name', 'Unknown')}")
            
            available_tables = get_available_tables()
            
            save_option = st.radio(
                "Choose option:",
                ["Create New Collection", "Add to Existing"] if available_tables else ["Create New Collection"]
            )
            
            selected_table = None
            
            if save_option == "Create New Collection":
                new_name = st.text_input("Collection Name:", placeholder="e.g., Competitor Ads")
                new_desc = st.text_input("Description:", placeholder="Optional description")
                notes = st.text_area("Notes (optional):", placeholder="Add notes about this ad...")
                
                if st.button("Create & Save", type="primary", use_container_width=True):
                    if new_name:
                        selected_table = create_ads_table(new_name, new_desc)
                        success, msg = save_ad_to_table(selected_table, ad_to_save, notes)
                        if success:
                            st.success(msg)
                            st.session_state.save_modal_ad = None
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                    else:
                        st.error("Please enter a collection name")
            
            else:  # Add to Existing
                table_options = [f"{desc if desc else name.replace('ads_', '').title()}" 
                                for name, desc, _ in available_tables]
                selected_idx = st.selectbox("Select Collection:", range(len(table_options)), 
                                           format_func=lambda x: table_options[x])
                selected_table = available_tables[selected_idx][0]
                
                notes = st.text_area("Notes (optional):", placeholder="Add notes about this ad...")
                
                if st.button("Save to Collection", type="primary", use_container_width=True):
                    success, msg = save_ad_to_table(selected_table, ad_to_save, notes)
                    if success:
                        st.success(msg)
                        st.session_state.save_modal_ad = None
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)
            
            if st.button("Cancel", use_container_width=True):
                st.session_state.save_modal_ad = None
                st.rerun()
            
            st.markdown("---")
            return  # Don't show navigation when save modal is open
    
    # Sidebar navigation
    with st.sidebar:
        st.title("🔍 Facebook Ads Search")
        st.markdown("---")
        
        tab = st.radio("Navigation", ["Search", "Saved Collections"])
        
        if tab == "Search":
            st.markdown("### Search Parameters")
            
            apify_token = st.text_input(
                "Apify API Token", 
                type="password",
                placeholder="Enter your Apify API token",
                help="Get your token from https://apify.com"
            )
            
            domain = st.text_input(
                "Domain URL", 
                placeholder="example.com",
                help="Enter domain without http:// or https://"
            )
            
            exact_phrase = st.checkbox(
                "Exact Phrase Match",
                value=False,
                help='Search for exact domain phrase'
            )
            
            country = st.selectbox(
                "Target Country", 
                ["US", "GB", "CA", "AU", "DE", "FR", "IN", "BR", "JP"],
                index=0
            )
            
            active_status = st.selectbox(
                "Ad Status",
                options=["active", "inactive", "all"],
                format_func=lambda x: x.capitalize()
            )
            
            count = st.slider(
                "Number of Ads", 
                min_value=1, 
                max_value=100, 
                value=10
            )
            
            st.markdown("### Date Filter (Optional)")
            
            use_date_filter = st.checkbox("Enable Date Filtering", value=False)
            
            if use_date_filter:
                today = date.today()
                six_months_ago = today - timedelta(days=180)
                
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input(
                        "From",
                        value=six_months_ago,
                        min_value=six_months_ago,
                        max_value=today
                    )
                
                with col2:
                    end_date = st.date_input(
                        "To", 
                        value=today,
                        min_value=six_months_ago,
                        max_value=today
                    )
            else:
                start_date = None
                end_date = None
            
            st.markdown("---")
            search_button = st.button("🚀 Search Ads", type="primary", use_container_width=True)
        
        else:  # Saved Collections navigation
            st.markdown("### 📁 Your Collections")
            available_tables = get_available_tables()
            
            if not available_tables:
                st.info("No saved collections yet")
            else:
                for table_name, desc, created in available_tables:
                    if st.button(
                        f"📁 {desc if desc else table_name.replace('ads_', '').title()}",
                        key=f"nav_{table_name}",
                        use_container_width=True
                    ):
                        st.session_state.selected_table = table_name
                    st.caption(f"Created: {created[:10] if created else 'Unknown'}")
            
            search_button = False
    
    # Main content area
    if tab == "Search":
        st.title("🔍 Facebook Ads Library Search")
        st.markdown("Search and analyze Facebook ads by domain")
        
        if search_button:
            if not apify_token:
                st.error("Please enter your Apify API token")
            elif not domain:
                st.error("Please enter a domain URL")
            elif use_date_filter and start_date > end_date:
                st.error("Start date must be before end date")
            else:
                # Show search info
                search_info = f"Searching for **{domain}**"
                if exact_phrase:
                    search_info += " (exact match)"
                search_info += f" • {active_status.capitalize()} ads • {country}"
                if use_date_filter:
                    search_info += f" • {start_date} to {end_date}"
                
                st.info(search_info)
                
                # Run search
                with st.spinner("Searching Facebook Ads Library..."):
                    ads = run_facebook_ads_scrape(
                        apify_token=apify_token, 
                        domain=domain, 
                        count=count, 
                        country=country, 
                        exact_phrase=exact_phrase,
                        active_status=active_status,
                        start_date=start_date if use_date_filter else None,
                        end_date=end_date if use_date_filter else None
                    )
                    st.session_state.current_ads = ads
                
                if ads:
                    st.success(f"Found {len(ads)} ads")
                    
                    # Display options
                    col1, col2 = st.columns([2, 1])
                    with col2:
                        view_mode = st.selectbox("View", ["Grid", "List"])
                    
                    st.markdown("---")
                    
                    # Display ads
                    if view_mode == "Grid":
                        cols = st.columns(3)
                        for i, ad in enumerate(ads):
                            with cols[i % 3]:
                                display_ad_card(ad, i, True)
                    else:
                        for i, ad in enumerate(ads):
                            display_ad_card(ad, i, True)
                            if i < len(ads) - 1:
                                st.markdown("---")
                else:
                    st.warning("No ads found for this search")
                    st.info("""
                        **Try adjusting your search:**
                        • Remove exact phrase matching
                        • Change the ad status filter
                        • Expand the date range
                        • Try a different domain
                    """)
        else:
            # Show recent ads if any
            if st.session_state.current_ads:
                st.info(f"Last search: {len(st.session_state.current_ads)} ads found")
                
                cols = st.columns(3)
                for i, ad in enumerate(st.session_state.current_ads[:6]):  # Show first 6
                    with cols[i % 3]:
                        display_ad_card(ad, i, True)
            else:
                st.info("Enter search parameters in the sidebar and click Search to find Facebook ads")
    
    else:  # Saved Collections tab
        st.title("💾 Saved Ad Collections")
        
        if st.session_state.selected_table:
            table_name = st.session_state.selected_table
            
            # Get table info
            available_tables = get_available_tables()
            table_info = next((t for t in available_tables if t[0] == table_name), None)
            
            if table_info:
                _, desc, created = table_info
                
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"### 📁 {desc if desc else table_name.replace('ads_', '').title()}")
                with col2:
                    if st.button("← Back", key="back_btn"):
                        st.session_state.selected_table = None
                        st.rerun()
                with col3:
                    if st.button("🗑️ Delete Collection", key="delete_collection"):
                        if delete_table(table_name):
                            st.success("Collection deleted!")
                            st.session_state.selected_table = None
                            time.sleep(1)
                            st.rerun()
                
                st.caption(f"Created: {created[:10] if created else 'Unknown'}")
                
                # Get saved ads
                saved_ads = get_saved_ads(table_name)
                
                if saved_ads:
                    st.write(f"**{len(saved_ads)} ads in this collection**")
                    
                    # Display options
                    col1, col2 = st.columns([2, 1])
                    with col2:
                        display_mode = st.selectbox("Display", ["Compact", "Full"])
                    
                    st.markdown("---")
                    
                    # Display saved ads
                    if display_mode == "Full":
                        cols = st.columns(3)
                        for i, ad in enumerate(saved_ads):
                            with cols[i % 3]:
                                # Delete button for individual ad
                                if st.button(f"🗑️", key=f"del_ad_{ad.get('id')}_{i}", help="Delete this ad"):
                                    delete_saved_ad(table_name, ad.get('id'))
                                    st.success("Ad deleted!")
                                    st.rerun()
                                
                                # Display the ad card
                                display_ad_card(ad, f"saved_{i}", False)
                                
                                # Show notes if any
                                if ad.get('notes'):
                                    st.info(f"📝 {ad.get('notes')}")
                                
                                # Show saved date
                                if ad.get('saved_at'):
                                    st.caption(f"Saved: {ad.get('saved_at')[:19]}")
                    else:  # Compact view
                        for i, ad in enumerate(saved_ads):
                            with st.expander(f"📄 {ad.get('page_name', 'Unknown')} - {ad.get('start_date', 'Date unknown')}"):
                                col1, col2 = st.columns([3, 1])
                                
                                with col1:
                                    st.write(f"**Page:** {ad.get('page_name', 'Unknown')}")
                                    if ad.get('display_url'):
                                        st.write(f"**URL:** {ad.get('display_url')}")
                                    if ad.get('cta_text'):
                                        st.write(f"**CTA:** {ad.get('cta_text')}")
                                    st.write(f"**Status:** {'🟢 Active' if ad.get('is_active') else '🔴 Inactive'}")
                                    
                                    if ad.get('notes'):
                                        st.markdown(f"**📝 Notes:** {ad.get('notes')}")
                                    
                                    st.caption(f"Saved: {ad.get('saved_at', '')[:19]}")
                                
                                with col2:
                                    if st.button(f"🗑️ Delete", key=f"del_compact_{ad.get('id')}"):
                                        delete_saved_ad(table_name, ad.get('id'))
                                        st.success("Ad deleted!")
                                        st.rerun()
                                    
                                    if ad.get('original_image_url'):
                                        try:
                                            st.image(ad.get('original_image_url'), width=150)
                                        except:
                                            st.write("🖼️ Image not available")
                                
                                # View on Facebook button
                                if ad.get('ad_archive_id'):
                                    fb_url = f"https://www.facebook.com/ads/library/?id={ad.get('ad_archive_id')}"
                                    st.markdown(f"[🔗 View on Facebook]({fb_url})")
                else:
                    st.info("No ads in this collection yet. Save some ads from your search results!")
            else:
                st.error("Collection not found")
                st.session_state.selected_table = None
                st.rerun()
        else:
            # Show all collections overview
            available_tables = get_available_tables()
            
            if not available_tables:
                st.info("No saved collections yet. Search for ads and save them to create your first collection!")
            else:
                st.markdown("### Your Collections")
                
                # Display collections as cards
                cols = st.columns(3)
                for i, (table_name, desc, created) in enumerate(available_tables):
                    with cols[i % 3]:
                        with st.container():
                            # Collection card
                            st.markdown(f"#### 📁 {desc if desc else table_name.replace('ads_', '').title()}")
                            
                            # Get count of ads in collection
                            ads_count = len(get_saved_ads(table_name))
                            st.write(f"**{ads_count} ads**")
                            st.caption(f"Created: {created[:10] if created else 'Unknown'}")
                            
                            col1, col2 = st.columns(2)
                            with col1:
                                if st.button("View", key=f"view_{table_name}", use_container_width=True):
                                    st.session_state.selected_table = table_name
                                    st.rerun()
                            with col2:
                                if st.button("Delete", key=f"del_{table_name}", use_container_width=True):
                                    if delete_table(table_name):
                                        st.success("Collection deleted!")
                                        time.sleep(1)
                                        st.rerun()
                            
                            st.markdown("---")

if __name__ == "__main__":
    main()
