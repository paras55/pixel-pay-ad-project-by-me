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
import hashlib
from io import BytesIO
import requests

# Assistant / image generation engine
try:
    from . import assistant_engine as ae  # when packaged
except Exception:
    import assistant_engine as ae  # when run directly

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

def init_generation_tables():
    """Create tables for uploads and generated images if they don't exist"""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            content_type TEXT,
            sha256 TEXT UNIQUE,
            data BLOB,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS generated_ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id INTEGER,
            session_id INTEGER,
            variant_id TEXT,
            prompt_json TEXT,
            variant_json TEXT,
            image_data BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        )
    ''')

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_generated_upload ON generated_ads(upload_id)")

    # Sessions table to group a batch generation
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS session_uploads (
            session_id INTEGER,
            upload_id INTEGER,
            PRIMARY KEY (session_id, upload_id),
            FOREIGN KEY(session_id) REFERENCES sessions(id),
            FOREIGN KEY(upload_id) REFERENCES uploads(id)
        )
    ''')

    # Ensure session_id column exists on generated_ads (for upgrade path)
    try:
        cursor.execute("PRAGMA table_info(generated_ads)")
        cols = [r[1] for r in cursor.fetchall()]
        if 'session_id' not in cols:
            cursor.execute("ALTER TABLE generated_ads ADD COLUMN session_id INTEGER")
    except Exception:
        pass

    # Create index on session_id after the column is guaranteed to exist
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_generated_session ON generated_ads(session_id)")
    except Exception:
        pass
    
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
# GENERATION STORAGE HELPERS
# =============================================================================

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def save_uploaded_image(filename: str, content_type: str, data: bytes) -> int:
    """Save an uploaded image and return its row id. Dedup by sha256."""
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    hash_hex = _sha256_bytes(data)
    try:
        cursor.execute('''
            INSERT INTO uploads (filename, content_type, sha256, data)
            VALUES (?, ?, ?, ?)
        ''', (filename, content_type, hash_hex, sqlite3.Binary(data)))
        upload_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return upload_id
    except sqlite3.IntegrityError:
        cursor.execute('SELECT id FROM uploads WHERE sha256 = ?', (hash_hex,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else -1

def list_uploaded_images() -> List[Dict[str, Any]]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, filename, content_type, uploaded_at FROM uploads ORDER BY uploaded_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": r[0], "filename": r[1], "content_type": r[2], "uploaded_at": r[3]}
        for r in rows
    ]

def get_upload_bytes(upload_id: int) -> Optional[bytes]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('SELECT data FROM uploads WHERE id = ?', (upload_id,))
    row = cursor.fetchone()
    conn.close()
    return bytes(row[0]) if row else None

def save_generated_image(upload_id: int, variant_id: str, prompt_json: dict, variant_json: dict, image_bytes: bytes) -> int:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO generated_ads (upload_id, session_id, variant_id, prompt_json, variant_json, image_data)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        upload_id,
        st.session_state.get('current_session_id'),
        str(variant_id) if variant_id is not None else None,
        json.dumps(prompt_json, ensure_ascii=False),
        json.dumps(variant_json, ensure_ascii=False),
        sqlite3.Binary(image_bytes)
    ))
    rowid = cursor.lastrowid
    conn.commit()
    conn.close()
    return rowid

def list_generated_for_upload(upload_id: int) -> List[Dict[str, Any]]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, variant_id, created_at FROM generated_ads
        WHERE upload_id = ? ORDER BY created_at DESC
    ''', (upload_id,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": r[0], "variant_id": r[1], "created_at": r[2]}
        for r in rows
    ]

def get_generated_image_bytes(gen_id: int) -> Optional[bytes]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('SELECT image_data FROM generated_ads WHERE id = ?', (gen_id,))
    row = cursor.fetchone()
    conn.close()
    return bytes(row[0]) if row else None

def create_session(source: str, note: str = "") -> int:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO sessions (source, note) VALUES (?, ?)', (source, note))
    sid = cursor.lastrowid
    conn.commit()
    conn.close()
    return sid

def link_session_uploads(session_id: int, upload_ids: List[int]):
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    for uid in upload_ids:
        cursor.execute('INSERT OR IGNORE INTO session_uploads (session_id, upload_id) VALUES (?, ?)', (session_id, uid))
    conn.commit()
    conn.close()

def list_session_uploads(session_id: int) -> List[int]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('SELECT upload_id FROM session_uploads WHERE session_id = ?', (session_id,))
    rows = [r[0] for r in cursor.fetchall()]
    conn.close()
    return rows

def list_sessions() -> List[Dict[str, Any]]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, source, note, created_at FROM sessions ORDER BY created_at DESC, id DESC')
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": r[0], "source": r[1], "note": r[2], "created_at": r[3]}
        for r in rows
    ]

def list_generated_for_session(session_id: int) -> List[Dict[str, Any]]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, upload_id, variant_id, created_at FROM generated_ads WHERE session_id = ? ORDER BY created_at DESC, id DESC', (session_id,))
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": r[0], "upload_id": r[1], "variant_id": r[2], "created_at": r[3]}
        for r in rows
    ]

def get_upload_meta(upload_id: int) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect('saved_ads.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, filename, content_type, uploaded_at FROM uploads WHERE id = ?', (upload_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "filename": row[1], "content_type": row[2], "uploaded_at": row[3]}

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
    .generate-sticky { position: sticky; top: 8px; z-index: 100; display: flex; justify-content: flex-end; background: var(--background-color, rgba(255,255,255,0.6)); padding: 4px 0; }
    .generate-sticky .stButton>button { width: auto; padding: 0.6rem 1.2rem; box-shadow: 0 6px 16px rgba(24,119,242,0.35); }
    .danger-zone {border:1px solid #e55353; padding:12px; border-radius:8px; background: #fff5f5;}
    </style>
""", unsafe_allow_html=True)

# Initialize database
init_database()
init_generation_tables()

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
    
    # Handle bulk save modal
    if st.session_state.get('pending_save_ads'):
        with st.sidebar:
            st.markdown("### 💾 Bulk Save Selected")
            st.markdown("---")
            num_sel = len(st.session_state.pending_save_ads)
            st.info(f"You are saving {num_sel} ad(s)")

            available_tables = get_available_tables()
            bulk_option = st.radio(
                "Save to:",
                ["Create New Collection", "Add to Existing"] if available_tables else ["Create New Collection"],
                key="bulk_save_option"
            )

            if bulk_option == "Create New Collection":
                bname = st.text_input("Collection Name", key="bulk_new_name", placeholder="e.g., Competitors Set A")
                bdesc = st.text_input("Description (optional)", key="bulk_new_desc")
                if st.button("Create & Save All", type="primary", use_container_width=True, key="bulk_create_and_save"):
                    if bname:
                        tbl = create_ads_table(bname, bdesc)
                        ok = 0
                        failed = 0
                        for ad in st.session_state.pending_save_ads:
                            success, _ = save_ad_to_table(tbl, ad)
                            if success:
                                ok += 1
                            else:
                                failed += 1
                        st.success(f"Saved {ok} of {num_sel} ad(s) to {tbl}")
                        if failed:
                            st.warning(f"{failed} ad(s) were duplicates or failed to save.")
                        st.session_state.pending_save_ads = None
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Please provide a collection name")
            else:
                options = available_tables
                idx = st.selectbox(
                    "Choose Collection",
                    list(range(len(options))),
                    format_func=lambda i: options[i][0],
                    key="bulk_existing_idx"
                )
                tbl = options[idx][0]
                if st.button("Save All to Selected Collection", type="primary", use_container_width=True, key="bulk_save_to_existing"):
                    ok = 0
                    failed = 0
                    for ad in st.session_state.pending_save_ads:
                        success, _ = save_ad_to_table(tbl, ad)
                        if success:
                            ok += 1
                        else:
                            failed += 1
                    st.success(f"Saved {ok} of {num_sel} ad(s) to {tbl}")
                    if failed:
                        st.warning(f"{failed} ad(s) were duplicates or failed to save.")
                    st.session_state.pending_save_ads = None
                    time.sleep(1)
                    st.rerun()

            if st.button("Cancel", use_container_width=True, key="bulk_cancel"):
                st.session_state.pending_save_ads = None
                st.rerun()

        return  # Stop normal rendering while bulk modal is open
    
    # Sidebar navigation
    with st.sidebar:
        st.title("🧰 Pixel Pay Ad Toolkit")
        st.markdown("---")
        
        tab = st.radio("Navigation", ["Search", "Saved Collections", "Generated Ads"])
        
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
        
        elif tab == "Saved Collections":  # Saved Collections navigation
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
        elif tab == "Generated Ads":
            st.markdown("### Generate with OpenAI Assistant")
            st.info("Using pre-configured Assistant and API key embedded in the app for testing.")
            size = st.selectbox("Image Size", ["512x512", "768x768", "1024x1024"], index=2)
            st.caption("Upload images in the main panel, select them, then click Generate ADS.")
            st.markdown("---")
            with st.expander("Danger Zone: Clear Database"):
                st.markdown('<div class="danger-zone">', unsafe_allow_html=True)
                st.write("This will permanently remove all uploads, sessions, and generated images.")
                col1, col2 = st.columns([1,1])
                with col1:
                    confirm = st.toggle("I understand the risk", key="clear_db_confirm_toggle")
                with col2:
                    pass
                phrase = st.text_input("Type CLEAR THE DATABASE to confirm", key="clear_db_phrase", placeholder="CLEAR THE DATABASE")
                disabled = not (confirm and phrase.strip().upper() == "CLEAR THE DATABASE")
                if st.button("Clear Database", key="clear_db_btn", disabled=disabled):
                    try:
                        import sqlite3 as _sql
                        conn = _sql.connect('saved_ads.db')
                        cur = conn.cursor()
                        cur.execute('DELETE FROM generated_ads')
                        cur.execute('DELETE FROM session_uploads')
                        cur.execute('DELETE FROM sessions')
                        cur.execute('DELETE FROM uploads')
                        conn.commit()
                        conn.close()
                        st.success("Database cleared.")
                    except Exception as e:
                        st.error(f"Failed to clear DB: {e}")
                st.markdown('</div>', unsafe_allow_html=True)
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
                    
                    # Sticky action bar first (always at top)
                    st.markdown('<div class="generate-sticky">', unsafe_allow_html=True)
                    colA, colB = st.columns([1,1])
                    with colA:
                        save_click = st.button("Save Selected to Collection", key="save_selected_btn_top")
                    with colB:
                        generate_direct = st.button("Generate ADS for Selected", key="generate_from_search_btn_persist")
                    st.markdown('</div>', unsafe_allow_html=True)

                    # Dedicated top status area (above cards)
                    status_slot = st.empty()

                    # Render cards with checkboxes
                    selected_from_search = []
                    if view_mode == "Grid":
                        cols = st.columns(3)
                        for i, ad in enumerate(ads):
                            with cols[i % 3]:
                                display_ad_card(ad, i, True)
                                if st.checkbox("Select", key=f"sel_search_{i}"):
                                    selected_from_search.append((i, ad))
                    else:
                        for i, ad in enumerate(ads):
                            display_ad_card(ad, i, True)
                            if st.checkbox("Select", key=f"sel_search_{i}"):
                                selected_from_search.append((i, ad))
                            if i < len(ads) - 1:
                                st.markdown("---")

                    # Save selected flow
                    if save_click:
                        if not selected_from_search:
                            st.warning("Select at least one ad to save.")
                        else:
                            # Store selected ads in session and open sidebar modal
                            st.session_state.pending_save_ads = [ad for _, ad in selected_from_search]
                            st.rerun()

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
            # Persist search results with selection checkboxes across reruns
            ads = st.session_state.current_ads
            if ads:
                st.success(f"Found {len(ads)} ads")

                col1, col2 = st.columns([2, 1])
                with col2:
                    view_mode = st.selectbox("View", ["Grid", "List"], key="search_view_mode_persist")

                st.markdown("---")

                # Sticky action bar first
                st.markdown('<div class="generate-sticky">', unsafe_allow_html=True)
                colA, colB = st.columns([1,1])
                with colA:
                    save_click_persist = st.button("Save Selected to Collection", key="save_selected_btn_persist")
                with colB:
                    generate_direct_persist = st.button("Generate ADS for Selected", key="generate_from_search_btn_persist")
                st.markdown('</div>', unsafe_allow_html=True)

                # Dedicated top status area (above cards)
                status_slot = st.empty()

                # Render cards with checkboxes
                selected_from_search = []
                if view_mode == "Grid":
                    cols = st.columns(3)
                    for i, ad in enumerate(ads):
                        with cols[i % 3]:
                            display_ad_card(ad, i, True)
                            if st.checkbox("Select", key=f"sel_search_{i}"):
                                selected_from_search.append((i, ad))
                else:
                    for i, ad in enumerate(ads):
                        display_ad_card(ad, i, True)
                        if st.checkbox("Select", key=f"sel_search_{i}"):
                            selected_from_search.append((i, ad))
                        if i < len(ads) - 1:
                            st.markdown("---")

                # Save selected flow (persisted branch)
                if save_click_persist:
                    if not selected_from_search:
                        st.warning("Select at least one ad to save.")
                    else:
                        st.session_state.pending_save_ads = [ad for _, ad in selected_from_search]
                        st.rerun()

                if generate_direct_persist and selected_from_search:
                    # Multi-step status (top)
                    status_obj = None
                    try:
                        status_obj = status_slot.status("Starting…", expanded=True)
                        status_obj.update(label="Fetching selected images…", state="running")
                    except Exception:
                        status_slot.markdown("**Starting…**\n\n- Fetching selected images…")
                    grouped_images = []
                    upload_ids = []
                    for i, ad in selected_from_search:
                        url = ad.get("original_image_url")
                        if not url:
                            st.warning(f"Selected ad {i+1} has no original image; skipping.")
                            continue
                        try:
                            resp = requests.get(url, timeout=20)
                            resp.raise_for_status()
                            img_bytes = resp.content
                            upload_id = save_uploaded_image(f"search_{i}.png", "image/png", img_bytes)
                            grouped_images.append((f"selected_{i}", img_bytes))
                            upload_ids.append(upload_id)
                        except Exception as e:
                            st.error(f"Failed to fetch selected ad {i+1}: {e}")
                    if grouped_images:
                        try:
                            if status_obj:
                                status_obj.update(label="Analyzing with Assistant…", state="running")
                            sid = create_session(source="search", note=f"{len(grouped_images)} images")
                            st.session_state.current_session_id = sid
                            link_session_uploads(sid, upload_ids)
                            json_prompt, variants_json = ae.analyze_images(None, None, grouped_images)
                            variants = variants_json.get("variant") if isinstance(variants_json, dict) else None
                            if not variants:
                                if status_obj:
                                    status_obj.update(label="No variants returned by assistant.", state="error")
                            else:
                                if status_obj:
                                    status_obj.update(label="Generating all variants…", state="running")
                                # Optionally show prompts for transparency
                                for v in variants:
                                    vid = v.get('id') or f"var_{variants.index(v)}"
                                    prompt_text = ae.build_prompt_text(json_prompt, v)
                                    with st.expander(f"Prompt for {vid}"):
                                        st.code(prompt_text, language="json")
                                for v in variants:
                                    vid = v.get('id') or f"var_{variants.index(v)}"
                                    img_out = ae.generate_single_variant_image(None, json_prompt, v, size="1024x1024")
                                    if img_out:
                                        save_generated_image(upload_ids[0], vid, json_prompt, v, img_out)
                                        st.toast(f"Image created for {vid}")
                                if status_obj:
                                    status_obj.update(label="Generation complete.", state="complete")
                                st.info("Go to the 'Generated Ads' tab to see originals and all generated variants for this run.")
                        except Exception as e:
                            variants = None
                            if status_obj:
                                status_obj.update(label=f"Analysis failed: {e}", state="error")
                            else:
                                status_slot.error(f"Analysis failed: {e}")
                    else:
                        variants = None

    elif tab == "Saved Collections":  # Saved Collections tab
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
                
                # Controls to save/generate for the entire collection
                st.markdown('<div class="generate-sticky">', unsafe_allow_html=True)
                colX, colY = st.columns([1,1])
                with colX:
                    gen_collection = st.button("Generate ADS for Collection", key="gen_collection_btn")
                with colY:
                    save_sel_to_other = st.button("Save Selected to Another Collection", key="save_sel_other_btn")
                st.markdown('</div>', unsafe_allow_html=True)

                status_slot = st.empty()

                selected_ads = []

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
                                
                                # Selection checkbox
                                checked = st.checkbox("Select", key=f"sel_saved_{ad.get('id')}")
                                if checked:
                                    selected_ads.append(ad)

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
                                    
                                    # Select checkbox
                                    if st.checkbox("Select", key=f"sel_saved_compact_{ad.get('id')}"):
                                        selected_ads.append(ad)
                                    
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

                # Save selected to another collection
                if save_sel_to_other and selected_ads:
                    st.session_state.pending_save_ads = selected_ads
                    st.rerun()

                # Generate for this collection (or selected subset)
                if gen_collection and (selected_ads or saved_ads):
                    targets = selected_ads if selected_ads else saved_ads
                    status_obj2 = status_slot.status("Starting collection generation…", expanded=True)
                    status_obj2.update(label="Fetching images…", state="running")
                    grouped_images = []
                    upload_ids = []
                    for i, ad in enumerate(targets):
                        url = ad.get("original_image_url")
                        if not url:
                            continue
                        try:
                            resp = requests.get(url, timeout=20)
                            resp.raise_for_status()
                            img_bytes = resp.content
                            upload_id = save_uploaded_image(f"collection_{i}.png", "image/png", img_bytes)
                            grouped_images.append((f"collection_{i}", img_bytes))
                            upload_ids.append(upload_id)
                        except Exception as e:
                            st.error(f"Failed fetch for ad {i+1}: {e}")
                    if grouped_images:
                        try:
                            status_obj2.update(label="Analyzing with Assistant…", state="running")
                            sid = create_session(source=f"collection:{table_name}", note=f"{len(grouped_images)} images")
                            st.session_state.current_session_id = sid
                            link_session_uploads(sid, upload_ids)
                            json_prompt, variants_json = ae.analyze_images(None, None, grouped_images)
                            variants = variants_json.get("variant") if isinstance(variants_json, dict) else None
                            if not variants:
                                status_obj2.update(label="No variants returned by assistant.", state="error")
                            else:
                                status_obj2.update(label="Generating all variants…", state="running")
                                # Optionally show prompts for transparency
                                for v in variants:
                                    vid = v.get('id') or f"var_{variants.index(v)}"
                                    prompt_text = ae.build_prompt_text(json_prompt, v)
                                    with st.expander(f"Prompt for {vid}"):
                                        st.code(prompt_text, language="json")
                                for v in variants:
                                    vid = v.get('id') or f"var_{variants.index(v)}"
                                    img_out = ae.generate_single_variant_image(None, json_prompt, v, size="1024x1024")
                                    if img_out:
                                        save_generated_image(upload_ids[0], vid, json_prompt, v, img_out)
                                        st.toast(f"Created image for {vid}")
                                status_obj2.update(label="Generation complete.", state="complete")
                        except Exception as e:
                            status_obj2.update(label=f"Analysis failed: {e}", state="error")

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

    elif tab == "Generated Ads":
        st.title("🎨 Generated Ads")
        st.markdown("Upload images, select the ones to process, then generate variants using your assistant. Originals appear together, followed by generated variants.")

        uploaded_files = st.file_uploader("Upload ad images", type=["png","jpg","jpeg","webp"], accept_multiple_files=True)
        if uploaded_files:
            for f in uploaded_files:
                data = f.read()
                _ = save_uploaded_image(f.name, getattr(f, 'type', 'image/png'), data)
            st.success(f"Uploaded {len(uploaded_files)} image(s)")
            st.experimental_rerun()

        uploads = list_uploaded_images()
        if not uploads:
            st.info("No uploads yet. Use the uploader above to add images.")
        else:
            selected_ids = []
            with st.container():
                cols = st.columns(3)
                for i, up in enumerate(uploads):
                    with cols[i % 3]:
                        img_bytes = get_upload_bytes(up["id"])  # preview
                        if img_bytes:
                            st.image(img_bytes, use_container_width=True)
                        selected = st.checkbox(up["filename"], key=f"sel_upload_{up['id']}")
                        if selected:
                            selected_ids.append(up["id"])

            if selected_ids:
                with st.container():
                    st.markdown('<div class="generate-sticky">', unsafe_allow_html=True)
                    clicked = st.button("Generate ADS", key="generate_ads_btn")
                    st.markdown('</div>', unsafe_allow_html=True)
                    if clicked:
                        pass

            if selected_ids and st.session_state.get("generate_ads_btn"):
                with st.spinner("Analyzing and generating variants..."):
                    # Create a session to group these uploads
                    sid = create_session(source="upload", note=f"{len(selected_ids)} images")
                    st.session_state.current_session_id = sid
                    link_session_uploads(sid, selected_ids)
                    # Analyze all selected uploads together
                    images_payload = []
                    for uid in selected_ids:
                        img_bytes = get_upload_bytes(uid)
                        if img_bytes:
                            images_payload.append((f"upload_{uid}", img_bytes))
                    json_prompt, variants_json = ae.analyze_images(None, None, images_payload)
                    variants = variants_json.get("variant") if isinstance(variants_json, dict) else None
                    if not variants or not isinstance(variants, list):
                        st.warning("Assistant did not return a variants list.")
                    else:
                        options = [v.get('id') or f'var_{i}' for i, v in enumerate(variants)]
                        selected_vars = st.multiselect("Select variants to generate", options, default=options, key=f"upload_var_select_{sid}")
                        for i, v in enumerate(variants):
                            vid = v.get('id') or f'var_{i}'
                            if vid not in selected_vars:
                                continue
                            prompt_text = ae.build_prompt_text(json_prompt, v)
                            with st.expander(f"Prompt for variant {vid}"):
                                st.code(prompt_text, language="json")
                            img_out = ae.generate_single_variant_image(None, json_prompt, v, size=size)
                            if img_out:
                                save_generated_image(selected_ids[0], vid, json_prompt, v, img_out)
                    for uid in selected_ids:
                        img_bytes = get_upload_bytes(uid)
                        if not img_bytes:
                            continue
                        try:
                            json_prompt, variants_json = ae.analyze_images(None, None, [(uid, img_bytes)])
                            variants = variants_json.get("variant") if isinstance(variants_json, dict) else None
                            if not variants or not isinstance(variants, list):
                                continue
                            for v in variants:
                                # Show the exact prompt used
                                prompt_text = ae.build_prompt_text(json_prompt, v)
                                with st.expander(f"Prompt for variant {v.get('id')}"):
                                    st.code(prompt_text, language="json")
                                img_out = ae.generate_single_variant_image(None, json_prompt, v, size=size)
                                if img_out:
                                    save_generated_image(uid, v.get("id"), json_prompt, v, img_out)
                        except Exception as gen_err:
                            st.error(f"Generation failed for an image: {gen_err}")
                st.success("Generation complete. Scroll down to see results in the gallery.")
                st.experimental_rerun()

        st.markdown("---")
        st.subheader("Sessions")
        sessions = list_sessions()
        if not sessions:
            st.info("No sessions yet. Generate some ads to create your first session.")
        else:
            # Choose session to view
            default_idx = 0
            idx = st.selectbox(
                "Select a session",
                options=list(range(len(sessions))),
                format_func=lambda i: f"Session {sessions[i]['id']} • {sessions[i]['source']} • {sessions[i]['created_at'][:19]}",
                index=default_idx
            )
            session = sessions[idx]
            st.markdown(f"**Session {session['id']}** · Source: {session['source']} · Created: {session['created_at'][:19]}")
            upload_ids = list_session_uploads(session['id'])
            if not upload_ids:
                st.info("This session has no original uploads recorded.")
            else:
                st.markdown("### Original Images")
                cols = st.columns(4)
                for i, uid in enumerate(upload_ids):
                    with cols[i % 4]:
                        meta = get_upload_meta(uid)
                        img_b = get_upload_bytes(uid) or b""
                        if img_b:
                            label = meta['filename'] if meta else f"upload_{uid}"
                            st.image(img_b, caption=label, use_container_width=True)
            st.markdown("---")
            st.markdown("### Generated Images")
            gens = list_generated_for_session(session['id'])
            if not gens:
                st.info("No generated images for this session yet.")
            else:
                cols = st.columns(3)
                for i, g in enumerate(gens):
                    with cols[i % 3]:
                        img_b = get_generated_image_bytes(g['id']) or b""
                        if img_b:
                            cap = f"Variant {g['variant_id'] or ''} • from upload {g['upload_id']}"
                            st.image(img_b, use_container_width=True, caption=cap)
                            st.download_button(
                                label="Download",
                                data=img_b,
                                file_name=f"session_{session['id']}_variant_{(g['variant_id'] or 'unknown')}.png",
                                mime="image/png",
                                key=f"dl_{session['id']}_{g['id']}"
                            )

if __name__ == "__main__":
    main()
