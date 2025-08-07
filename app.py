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
    }

# =============================================================================
# STREAMLIT APP
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

def display_ad_card(ad, index):
    """Display enhanced ad card with improved UI"""
    
    # Card container with styling
    with st.container():
        st.markdown(
            f"""
            <div style="
                border: 1px solid #e0e0e0;
                border-radius: 12px;
                padding: 20px;
                margin: 16px 0;
                background: white;
                box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            ">
            """, 
            unsafe_allow_html=True
        )
        
        col1, col2 = st.columns([1, 2])
        
        with col1:
            # Image section with original logic
            image_url = ad.get("original_image_url")
            
            if image_url:
                try:
                    st.image(
                        image_url, 
                        width=280,
                        caption="Ad Creative"
                    )
                except Exception as e:
                    st.markdown(
                        """
                        <div style="
                            width: 280px;
                            height: 200px;
                            background: #f5f5f5;
                            border: 2px dashed #ccc;
                            border-radius: 8px;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            color: #666;
                            font-size: 14px;
                        ">
                            🖼️ Image Error
                        </div>
                        """, 
                        unsafe_allow_html=True
                    )
            else:
                st.markdown(
                    """
                    <div style="
                        width: 280px;
                        height: 200px;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        border-radius: 8px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        color: white;
                        font-size: 16px;
                        font-weight: bold;
                    ">
                        📱 No Image Available
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
        
        with col2:
            # Header section
            page_name = ad.get("page_name") or "Unknown Page"
            st.markdown(f"### 📄 {page_name}")
            
            # Status badge
            is_active = ad.get("is_active")
            if is_active is not None:
                status = "🟢 Active" if is_active else "🔴 Inactive"
                st.markdown(f"**Status:** {status}")
            
            # Key information with clickable ad link
            ad_id = ad.get("ad_archive_id") or "N/A"
            if ad_id != "N/A":
                ad_url = f"https://www.facebook.com/ads/library/?id={ad_id}"
                st.markdown(f"**Ad ID:** `{ad_id}` | [🔗 View on Facebook]({ad_url})")
            else:
                st.markdown(f"**Ad ID:** `{ad_id}`")
            
            page_id = ad.get("page_id") or "N/A"  
            st.markdown(f"**Page ID:** `{page_id}`")
            
            # Categories with styling
            categories = ad.get("categories")
            if categories:
                st.markdown(f"**Categories:** *{categories}*")
            
            # CTA Section
            cta_text = ad.get("cta_text")
            cta_type = ad.get("cta_type")
            if cta_text:
                st.markdown(f"**Call-to-Action:** `{cta_text}`")
                if cta_type:
                    st.markdown(f"**CTA Type:** {cta_type}")
            
            # Display URL and Website URL
            display_url = ad.get("display_url")
            if display_url:
                st.markdown(f"**Display URL:** {display_url}")
            
            website_url = ad.get("website_url")
            if website_url:
                st.markdown(f"**Website URL:** [{website_url}]({website_url})")
            
            # Link with clickable format (fallback)
            link_url = ad.get("link_url")
            if link_url and link_url != website_url:
                st.markdown(f"**Landing Page:** [{link_url}]({link_url})")
            
            # Dates section
            col_date1, col_date2 = st.columns(2)
            with col_date1:
                start_date = ad.get("start_date")
                if start_date:
                    st.markdown(f"**Started:** {start_date}")
            with col_date2:
                end_date = ad.get("end_date")
                if end_date:
                    st.markdown(f"**Ended:** {end_date}")
            
            # Additional metadata in expander
            with st.expander("📊 Additional Details"):
                collation_count = ad.get("collation_count")
                if collation_count:
                    st.write(f"**Similar Ads:** {collation_count}")
                
                collation_id = ad.get("collation_id")
                if collation_id:
                    st.write(f"**Group ID:** {collation_id}")
                
                entity_type = ad.get("entity_type")
                if entity_type:
                    st.write(f"**Entity Type:** {entity_type}")
                
                total_active_time = ad.get("total_active_time")
                if total_active_time:
                    st.write(f"**Total Active Time:** {total_active_time}")
                
                page_profile_uri = ad.get("page_profile_uri")
                if page_profile_uri:
                    st.write(f"**Page Profile:** {page_profile_uri}")
                
                state_label = ad.get("state_media_run_label")
                if state_label:
                    st.write(f"**State Label:** {state_label}")
        
        st.markdown("</div>", unsafe_allow_html=True)

def main():
    """Enhanced Streamlit app with improved UI"""
    
    st.set_page_config(
        page_title="Facebook Ads Domain Search", 
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Header with styling
    st.markdown(
        """
        <div style="
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 2rem;
            border-radius: 10px;
            margin-bottom: 2rem;
            text-align: center;
        ">
            <h1 style="color: white; margin: 0;">🔍 Facebook Ads Domain Search</h1>
            <p style="color: rgba(255,255,255,0.8); margin: 0.5rem 0 0 0;">
                Find Facebook ads linking to your domain using the same extraction logic as the original app
            </p>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    # Search form with improved styling
    with st.form("search_form"):
        st.markdown("### 🎯 Search Parameters")
        
        # Basic parameters
        col1, col2 = st.columns(2)
        
        with col1:
            apify_token = st.text_input(
                "🔑 Apify API Token", 
                type="password",
                placeholder="Enter your Apify API token",
                help="Get your token from https://apify.com"
            )
            domain = st.text_input(
                "🌐 Domain URL", 
                placeholder="example.com",
                help="Enter domain without http:// or https://"
            )
            
            # Exact phrase match checkbox
            exact_phrase = st.checkbox(
                "🎯 Exact Phrase Match",
                value=False,
                help='Search for exact domain phrase (adds quotes around domain: "example.com")'
            )
        
        with col2:
            count = st.number_input(
                "📊 Number of Ads", 
                min_value=1, 
                max_value=100, 
                value=10,
                help="Maximum 100 ads per search"
            )
            country = st.selectbox(
                "🌍 Target Country", 
                ["US", "GB", "CA", "AU", "DE", "FR", "IN", "BR", "JP"],
                index=0,
                help="Country where ads are targeted"
            )
            
            # Active/Inactive status dropdown
            active_status = st.selectbox(
                "⚡ Ad Status Filter",
                [
                    ("Active Ads Only", "active"),
                    ("Inactive Ads Only", "inactive"), 
                    ("All Ads", "all")
                ],
                format_func=lambda x: x[0],
                index=0,
                help="Filter ads by their current status"
            )
        
        # Date range selection with calendar
        st.markdown("#### 📅 Date Range (Optional)")
        
        # Calculate date limits (6 months back)
        today = date.today()
        six_months_ago = today - timedelta(days=180)
        
        col_date1, col_date2, col_date3 = st.columns([1, 1, 1])
        
        with col_date1:
            use_date_filter = st.checkbox(
                "Enable Date Filtering", 
                value=False,
                help="Filter ads by start date range"
            )
        
        with col_date2:
            start_date = st.date_input(
                "From Date",
                value=six_months_ago,
                min_value=six_months_ago,
                max_value=today,
                help="Earliest ad start date to include (only used if date filtering is enabled)"
            )
        
        with col_date3:
            end_date = st.date_input(
                "To Date", 
                value=today,
                min_value=six_months_ago,
                max_value=today,
                help="Latest ad start date to include (only used if date filtering is enabled)"
            )
        
        # Show info about date filter status
        if use_date_filter:
            st.info(f"📅 Will filter ads with start dates between **{start_date}** and **{end_date}**")
        else:
            st.info("📅 Date filtering is disabled - will return all ads regardless of date")
        
        # Validate date range
        if use_date_filter and start_date > end_date:
            st.error("❌ Start date must be before end date")
        
        selected_active_status = active_status[1]
        
        submitted = st.form_submit_button(
            "🚀 Search Ads", 
            type="primary",
            use_container_width=True
        )
    
    # Results section
    if submitted:
        if not apify_token:
            st.error("🔑 Please enter your Apify API token")
            return
        
        if not domain:
            st.error("🌐 Please enter a domain URL")
            return
        
        if use_date_filter and start_date > end_date:
            st.error("📅 Please select a valid date range")
            return
        
        # Loading with progress
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        status_text.text("🔍 Initializing search...")
        progress_bar.progress(25)
        
        # Build search description
        search_desc = f"{domain}"
        if exact_phrase:
            search_desc += " (exact phrase)"
        search_desc += f" - {active_status[0]}"
        if use_date_filter:
            search_desc += f" ({start_date} to {end_date})"
        
        status_text.text(f"📡 Searching for ads: {search_desc}...")
        progress_bar.progress(50)
        
        ads = run_facebook_ads_scrape(
            apify_token=apify_token, 
            domain=domain, 
            count=count, 
            country=country, 
            exact_phrase=exact_phrase,
            active_status=selected_active_status,
            start_date=start_date if use_date_filter else None,
            end_date=end_date if use_date_filter else None
        )
        
        progress_bar.progress(100)
        status_text.empty()
        progress_bar.empty()
        
        if ads:
            st.success(f"✅ Found {len(ads)} ads: {search_desc}")
            
            # Results summary with enhanced info
            st.markdown("---")
            col_summary1, col_summary2, col_summary3, col_summary4 = st.columns(4)
            with col_summary1:
                st.metric("📊 Total Ads", len(ads))
            with col_summary2:
                st.metric("🌍 Country", country)
            with col_summary3:
                match_type = "Exact" if exact_phrase else "Broad"
                st.metric("🎯 Match Type", match_type)
            with col_summary4:
                st.metric("⚡ Status", active_status[0].split()[0])
            
            # Show date range if used
            if use_date_filter:
                st.info(f"📅 Filtered by start date: **{start_date}** to **{end_date}**")
            
            st.markdown("### 📋 Search Results")
            
            # Display ads
            for i, ad in enumerate(ads):
                display_ad_card(ad, i)
                
        else:
            st.warning(f"⚠️ No ads found: {search_desc}")
            suggestions = [
                "Try removing the exact phrase match",
                "Expand the date range or remove date filtering", 
                "Change from active to all ads",
                "Try a different domain or country"
            ]
            st.info("💡 **Suggestions:**\n" + "\n".join([f"• {s}" for s in suggestions]))
    
    # Footer with instructions
    with st.expander("ℹ️ How to Use This App"):
        st.markdown(
            """
            ### 🚀 Getting Started
            1. **Get Apify Token**: Sign up at [apify.com](https://apify.com) and get your API token
            2. **Enter Domain**: Type the domain you want to search (e.g., "amazon.com", "shopify.com")
            3. **Configure Options**:
               - **Exact Phrase**: Check to search for exact domain match (adds quotes)
               - **Ad Status**: Choose Active, Inactive, or All ads
               - **Date Range**: Optionally filter by ad start date (up to 6 months back)
               - **Country & Count**: Select target country and number of results
            4. **Search**: Click "Search Ads" to find Facebook ads
            
            ### 🎯 Search Features
            - **Broad Match**: `example.com` finds ads containing the domain anywhere
            - **Exact Match**: `"example.com"` finds ads with exact domain phrase
            - **Status Filter**: 
              - Active: Currently running ads
              - Inactive: Ended or paused ads  
              - All: Both active and inactive
            - **Date Range**: Filter ads by when they started running (optional)
            
            ### 📅 Date Filtering
            - **Range**: Up to 6 months back from today
            - **Client-side**: Filters results after API retrieval for precise control
            - **Optional**: Leave unchecked to get all available ads
            
            ### 🖼️ Image Extraction
            This app uses the **exact same image extraction logic** as the original Facebook Ads Explorer:
            - Primary: `snapshot.images[].original_image_url`
            - Fallback: Direct image fields like `imageUrl`, `thumbnailUrl`
            - Enhanced: Creatives and media arrays
            
            ### 📊 What You'll See
            Each ad card displays:
            - **Ad Creative**: Original image from Facebook
            - **Page Info**: Who's running the ad
            - **CTA Details**: Call-to-action text and type  
            - **Links**: Where the ad leads
            - **Dates**: When the ad started/ended
            - **Metadata**: Categories, status, and more
            
            ### 🔧 Troubleshooting
            - **No images**: Some ads may not have accessible images
            - **No results**: Domain might not have active Facebook ads
            - **API errors**: Check your Apify token and internet connection
            """
        )

if __name__ == "__main__":
    main()
