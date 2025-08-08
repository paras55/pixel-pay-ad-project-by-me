"""
Facebook Ads Domain Search - Streamlit App
Uses the same image extraction logic as the original code with improved UI
"""

import streamlit as st
import json
from datetime import datetime, timedelta, timezone, date
from apify_client import ApifyClient
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote_plus

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Facebook Ads Domain Search", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for modern UI
st.markdown("""
    <style>
    /* Main container padding */
    .main {
        padding: 0rem 1rem;
    }
    
    /* Card styling */
    .ad-card {
        background: white;
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        transition: all 0.3s ease;
        height: 100%;
        display: flex;
        flex-direction: column;
    }
    
    .ad-card:hover {
        box-shadow: 0 4px 16px rgba(0,0,0,0.15);
        transform: translateY(-2px);
    }
    
    /* Media container */
    .media-container {
        width: 100%;
        height: 200px;
        background: #f0f2f5;
        position: relative;
        overflow: hidden;
    }
    
    /* Card content */
    .card-content {
        padding: 12px;
        flex-grow: 1;
        display: flex;
        flex-direction: column;
    }
    
    /* Page name styling */
    .page-name {
        font-weight: 600;
        font-size: 14px;
        color: #1c1e21;
        margin-bottom: 4px;
        display: -webkit-box;
        -webkit-line-clamp: 1;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    
    /* Meta info */
    .meta-info {
        font-size: 12px;
        color: #65676b;
        margin-bottom: 8px;
    }
    
    /* CTA button */
    .cta-button {
        display: inline-block;
        padding: 4px 12px;
        background: #1877f2;
        color: white;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 500;
        text-decoration: none;
        margin-top: 8px;
    }
    
    /* Status badge */
    .status-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 11px;
        font-weight: 500;
        margin-left: 8px;
    }
    
    .status-active {
        background: #e3f2e3;
        color: #1a7f1a;
    }
    
    .status-inactive {
        background: #fce4e4;
        color: #c73232;
    }
    
    /* Grid adjustments */
    .stButton > button {
        width: 100%;
        background: #1877f2;
        color: white;
        border: none;
        padding: 0.5rem 1rem;
        border-radius: 8px;
        font-weight: 500;
    }
    
    .stButton > button:hover {
        background: #166fe5;
    }
    
    /* Sidebar styling */
    .css-1d391kg, .st-emotion-cache-1d391kg {
        padding-top: 1rem;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    </style>
""", unsafe_allow_html=True)

# =============================================================================
# DATE FILTERING HELPER
# =============================================================================

def is_date_in_range(date_str: str, start_date: date, end_date: date) -> bool:
    """Check if date falls within selected date range"""
    if not date_str:
        return True
    
    try:
        # Parse the date (handle various formats)
        if 'T' in date_str:
            ad_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
        else:
            ad_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        return start_date <= ad_date <= end_date
    except Exception:
        return True  # Include if we can't parse the date

# =============================================================================
# IMAGE EXTRACTION LOGIC (Same as original code)
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
    
    # Get images from snapshot
    imgs = snap.get("images")
    if isinstance(imgs, dict):
        imgs = [imgs]
    elif not isinstance(imgs, (list, tuple)):
        imgs = []
    
    # Check image URL fields in priority order
    for im in imgs:
        if not isinstance(im, dict):
            continue
        for k in ("original_image_url", "original_picture_url", "original_picture", "url", "src"):
            v = im.get(k)
            if v:
                return v
    return None

def extract_primary_media(item: dict) -> Tuple[Optional[str], Optional[str]]:
    """Extract primary media with fallback logic"""
    # Try original image URL first
    oi = get_original_image_url(item)
    if oi:
        return "image", oi
    
    # Direct image fields
    img_keys = ["imageUrl", "image_url", "thumbnailUrl", "thumbnail_url", "image"]
    for k in img_keys:
        if item.get(k):
            return "image", item[k]
    
    # Direct video fields
    vid_keys = ["videoUrl", "video_url", "video"]
    for k in vid_keys:
        if item.get(k):
            return "video", item[k]
    
    # Creatives array
    creatives = item.get("creatives") or item.get("media") or []
    if isinstance(creatives, dict):
        creatives = [creatives]
    if isinstance(creatives, (list, tuple)):
        for c in creatives:
            if not isinstance(c, dict):
                continue
            for k in img_keys:
                if c.get(k):
                    return "image", c[k]
            for k in vid_keys:
                if c.get(k):
                    return "video", c[k]
    
    # Media URLs array
    media_urls = item.get("mediaUrls") or item.get("media_urls")
    if isinstance(media_urls, (list, tuple)) and media_urls:
        return "image", media_urls[0]
    
    return None, None

def extract_selected_fields(item: dict) -> dict:
    """Extract fields using original code logic"""
    snap = _get_snapshot_dict(item)
    
    # Cards data
    card0 = None
    cards = snap.get("cards")
    if isinstance(cards, list) and cards:
        if isinstance(cards[0], dict):
            card0 = cards[0]
    elif isinstance(cards, dict):
        card0 = cards
    
    # Page categories
    pgcat0 = None
    page_categories = snap.get("page_categories")
    if isinstance(page_categories, list) and page_categories:
        if isinstance(page_categories[0], dict):
            pgcat0 = page_categories[0]
    elif isinstance(page_categories, dict):
        pgcat0 = page_categories
    
    # Link URL
    link_url = snap.get("link_url")
    if not link_url and isinstance(card0, dict):
        link_url = card0.get("link_url")
    
    # Extract Display URL (from snapshot/caption) and Website URL (from snapshot)
    display_url = snap.get("caption")
    website_url = snap.get("link_url") or snap.get("website") or snap.get("url")
    
    # Categories display
    categories = item.get("categories")
    if isinstance(categories, (list, tuple)):
        categories_disp = ", ".join(str(c) for c in categories)
    else:
        categories_disp = categories
    
    # Get image URL with fallback logic
    image_url = get_original_image_url(item)
    if not image_url:
        img_keys = ["imageUrl", "image_url", "thumbnailUrl", "thumbnail_url", "image"]
        for k in img_keys:
            if item.get(k):
                image_url = item[k]
                break
    
    # Extract video URL using similar logic
    video_url = None
    
    # Check snapshot for video URLs
    videos = snap.get("videos")
    if isinstance(videos, dict):
        videos = [videos]
    elif not isinstance(videos, (list, tuple)):
        videos = []
    
    # Check video URL fields in priority order
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
    
    # Direct video fields fallback
    if not video_url:
        vid_keys = ["videoUrl", "video_url", "video", "video_hd_url", "video_sd_url"]
        for k in vid_keys:
            if item.get(k):
                video_url = item[k]
                break
            if snap.get(k):
                video_url = snap[k]
                break
    
    # Check creatives for video
    if not video_url:
        creatives = item.get("creatives") or item.get("media") or []
        if isinstance(creatives, dict):
            creatives = [creatives]
        if isinstance(creatives, (list, tuple)):
            for c in creatives:
                if not isinstance(c, dict):
                    continue
                for k in vid_keys:
                    if c.get(k):
                        video_url = c[k]
                        break
                if video_url:
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
    
    # Handle exact phrase search
    if exact_phrase:
        # Add quotes around domain for exact phrase
        domain_query = f'"{domain.strip()}"'
        search_type = "keyword_exact_phrase"
    else:
        domain_query = domain.strip()
        search_type = "keyword_unordered"
    
    # URL encode the query
    domain_encoded = quote_plus(domain_query)
    
    # Build the base URL with correct search_type
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
    
    # Add date filter parameters if dates are provided
    if start_date and end_date:
        url += f"&start_date[min]={start_date.strftime('%Y-%m-%d')}"
        url += f"&start_date[max]={end_date.strftime('%Y-%m-%d')}"

    print(f"Running search for domain: {url}")
    
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
        
        # Process items using original extraction logic
        processed_items = []
        for item in items:
            processed_item = extract_selected_fields(item)
            
            # Client-side date filtering if date range is specified
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

def display_ad_card(ad, index):
    """Display ad card in modern grid layout"""
    
    # Get ad details
    page_name = ad.get("page_name") or "Unknown Page"
    ad_id = ad.get("ad_archive_id") or "N/A"
    is_active = ad.get("is_active")
    cta_text = ad.get("cta_text")
    cta_type = ad.get("cta_type")
    start_date = ad.get("start_date")
    end_date = ad.get("end_date")
    image_url = ad.get("original_image_url")
    video_url = ad.get("video_url")
    website_url = ad.get("website_url")
    display_url = ad.get("display_url")
    link_url = ad.get("link_url")
    page_id = ad.get("page_id")
    categories = ad.get("categories")
    collation_count = ad.get("collation_count")
    collation_id = ad.get("collation_id")
    entity_type = ad.get("entity_type")
    page_entity_type = ad.get("page_entity_type")
    page_profile_picture_url = ad.get("page_profile_picture_url")
    page_profile_uri = ad.get("page_profile_uri")
    state_media_run_label = ad.get("state_media_run_label")
    total_active_time = ad.get("total_active_time")
    
    # Container for the card
    with st.container():
        # Display media first (video or image)
        if video_url:
            try:
                st.video(video_url)
            except Exception as e:
                # Fallback to image if video fails
                if image_url:
                    try:
                        st.image(image_url, use_column_width=True)
                    except:
                        st.markdown("""
                            <div style="width: 100%; height: 200px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                                        border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                                <span style="color: white; font-size: 16px;">📹 Video Error</span>
                            </div>
                        """, unsafe_allow_html=True)
                else:
                    st.markdown("""
                        <div style="width: 100%; height: 200px; background: #f0f2f5; 
                                    border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                            <span style="color: #65676b; font-size: 48px;">▶</span>
                        </div>
                    """, unsafe_allow_html=True)
        elif image_url:
            try:
                st.image(image_url, use_column_width=True)
            except Exception as e:
                st.markdown("""
                    <div style="width: 100%; height: 200px; background: #f0f2f5; 
                                border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                        <span style="color: #65676b; font-size: 16px;">🖼️ Image not available</span>
                    </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("""
                <div style="width: 100%; height: 200px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                            border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                    <span style="color: white; font-size: 16px; font-weight: bold;">No Media Available</span>
                </div>
            """, unsafe_allow_html=True)
        
        # Card info section
        st.markdown(f"""
            <div style="padding: 12px 0; border-bottom: 1px solid #e4e6eb;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px;">
                    <span style="font-weight: 600; font-size: 14px; color: #1c1e21;">
                        {page_name[:30]}{'...' if len(page_name) > 30 else ''}
                    </span>
                    <span style="padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 500;
                                background: {'#e3f2e3' if is_active else '#fce4e4'}; 
                                color: {'#1a7f1a' if is_active else '#c73232'};">
                        {'Active' if is_active else 'Inactive'}
                    </span>
                </div>
                <div style="font-size: 12px; color: #65676b;">
                    {f'{start_date}' if start_date else 'Date unknown'}
                </div>
                {f'<div style="font-size: 12px; color: #1877f2; margin-top: 4px;">{display_url}</div>' if display_url else ''}
                {f'<div style="margin-top: 8px;"><span style="background: #1877f2; color: white; padding: 4px 12px; border-radius: 6px; font-size: 12px; font-weight: 500;">{cta_text}</span></div>' if cta_text else ''}
            </div>
        """, unsafe_allow_html=True)
        
        # View details expander with ALL information
        with st.expander("📊 View Full Details"):
            # Main information
            st.markdown("#### 📄 Page Information")
            col1, col2 = st.columns(2)
            
            with col1:
                st.write(f"**Page Name:** {page_name}")
                if page_id:
                    st.write(f"**Page ID:** `{page_id}`")
                if is_active is not None:
                    status = "🟢 Active" if is_active else "🔴 Inactive"
                    st.write(f"**Status:** {status}")
            
            with col2:
                if ad_id != "N/A":
                    st.write(f"**Ad ID:** `{ad_id}`")
                    fb_url = f"https://www.facebook.com/ads/library/?id={ad_id}"
                    st.markdown(f"[🔗 View on Facebook]({fb_url})")
                if categories:
                    st.write(f"**Categories:** *{categories}*")
            
            # CTA Information
            if cta_text or cta_type:
                st.markdown("#### 🎯 Call-to-Action")
                if cta_text:
                    st.write(f"**CTA Text:** `{cta_text}`")
                if cta_type:
                    st.write(f"**CTA Type:** {cta_type}")
            
            # URLs Section
            st.markdown("#### 🔗 URLs")
            if display_url:
                st.write(f"**Display URL:** {display_url}")
            if website_url:
                st.write(f"**Website URL:** [{website_url}]({website_url})")
            if link_url and link_url != website_url:
                st.write(f"**Landing Page:** [{link_url}]({link_url})")
            
            # Dates Section
            st.markdown("#### 📅 Timeline")
            col_date1, col_date2 = st.columns(2)
            with col_date1:
                if start_date:
                    st.write(f"**Started:** {start_date}")
            with col_date2:
                if end_date:
                    st.write(f"**Ended:** {end_date}")
            
            if total_active_time:
                st.write(f"**Total Active Time:** {total_active_time}")
            
            # Additional Metadata
            st.markdown("#### 📊 Additional Metadata")
            
            col_meta1, col_meta2 = st.columns(2)
            with col_meta1:
                if collation_count:
                    st.write(f"**Similar Ads:** {collation_count}")
                if collation_id:
                    st.write(f"**Group ID:** {collation_id}")
                if entity_type:
                    st.write(f"**Entity Type:** {entity_type}")
                if page_entity_type:
                    st.write(f"**Page Entity Type:** {page_entity_type}")
            
            with col_meta2:
                if page_profile_uri:
                    st.write(f"**Page Profile:** {page_profile_uri}")
                if state_media_run_label:
                    st.write(f"**State Label:** {state_media_run_label}")
                if page_profile_picture_url:
                    st.write(f"**Profile Picture:** [View]({page_profile_picture_url})")
            
            # Media URLs (for debugging/reference)
            if video_url or image_url:
                st.markdown("#### 🖼️ Media Links")
                if video_url:
                    st.write(f"**Video URL:** {video_url[:100]}{'...' if len(video_url) > 100 else ''}")
                if image_url:
                    st.write(f"**Image URL:** {image_url[:100]}{'...' if len(image_url) > 100 else ''}")

# =============================================================================
# MAIN APP
# =============================================================================

def main():
    """Main Streamlit app"""
    
    # Sidebar for all controls
    with st.sidebar:
        st.title("🔍 Facebook Ads Search")
        st.markdown("---")
        
        # API Token
        apify_token = st.text_input(
            "Apify API Token", 
            type="password",
            placeholder="Enter your Apify API token",
            help="Get your token from https://apify.com"
        )
        
        st.markdown("### Search Parameters")
        
        # Domain input
        domain = st.text_input(
            "Domain URL", 
            placeholder="example.com",
            help="Enter domain without http:// or https://"
        )
        
        # Exact phrase match
        exact_phrase = st.checkbox(
            "Exact Phrase Match",
            value=False,
            help='Search for exact domain phrase'
        )
        
        # Country selection
        country = st.selectbox(
            "Target Country", 
            ["US", "GB", "CA", "AU", "DE", "FR", "IN", "BR", "JP"],
            index=0
        )
        
        # Ad status
        active_status = st.selectbox(
            "Ad Status",
            options=["active", "inactive", "all"],
            format_func=lambda x: x.capitalize()
        )
        
        # Number of ads
        count = st.slider(
            "Number of Ads", 
            min_value=1, 
            max_value=100, 
            value=10
        )
        
        st.markdown("### Date Filter")
        
        # Date filtering
        use_date_filter = st.checkbox("Enable Date Filtering", value=False)
        
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
        
        # Search button
        st.markdown("---")
        search_button = st.button("🚀 Search Ads", type="primary", use_container_width=True)
    
    # Main content area
    # Header
    st.markdown("""
        <h1 style="font-size: 24px; font-weight: 600; margin-bottom: 8px;">
            Facebook Ads Library
        </h1>
        <p style="color: #65676b; font-size: 14px; margin-bottom: 20px;">
            Search and analyze Facebook ads by domain
        </p>
    """, unsafe_allow_html=True)
    
    # Results section
    if search_button:
        if not apify_token:
            st.error("Please enter your Apify API token")
            return
        
        if not domain:
            st.error("Please enter a domain URL")
            return
        
        if use_date_filter and start_date > end_date:
            st.error("Start date must be before end date")
            return
        
        # Show search info
        search_info = f"Searching for **{domain}**"
        if exact_phrase:
            search_info += " (exact match)"
        search_info += f" • {active_status.capitalize()} ads"
        if use_date_filter:
            search_info += f" • {start_date} to {end_date}"
        
        st.info(search_info)
        
        # Run search with spinner
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
        
        if ads:
            # Results header
            st.success(f"Found {len(ads)} ads")
            
            # Filter/sort bar (placeholder for future features)
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                st.markdown(f"**{len(ads)} Results**")
            with col2:
                sort_by = st.selectbox("Sort by", ["Newest", "Oldest"], label_visibility="collapsed")
            with col3:
                view_mode = st.selectbox("View", ["Grid", "List"], label_visibility="collapsed")
            
            st.markdown("---")
            
            # Display ads in grid
            if view_mode == "Grid":
                # Create columns for grid layout (4 columns like in screenshot)
                cols = st.columns(4)
                for i, ad in enumerate(ads):
                    with cols[i % 4]:
                        display_ad_card(ad, i)
            else:
                # List view (alternative)
                for i, ad in enumerate(ads):
                    with st.container():
                        display_ad_card(ad, i)
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
        # Welcome message when no search has been performed
        st.markdown("""
            <div style="text-align: center; padding: 60px 20px; color: #65676b;">
                <h2 style="font-size: 20px; margin-bottom: 12px;">Welcome to Facebook Ads Search</h2>
                <p style="font-size: 14px;">
                    Enter a domain in the sidebar and click Search to find Facebook ads
                </p>
            </div>
        """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
