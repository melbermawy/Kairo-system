# Apify Actor Samples

This document contains one input/output example for each Apify actor used in the Kairo system.

---

## 1. apify/instagram-reel-scraper

**Actor ID:** `apify/instagram-reel-scraper`

**Description:** Scrapes Instagram Reels/Videos with detailed metadata including comments, engagement metrics, and transcripts.

**Source:** [Apify Instagram Reel Scraper](https://apify.com/apify/instagram-reel-scraper/input-schema)

### Available Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `directUrls` | array | Optional | — | Instagram URLs to scrape (profile URLs, reel URLs, or post URLs) |
| `username` | array | Optional | — | Instagram usernames to scrape reels from |
| `resultsLimit` | integer | Optional | 200 | Maximum number of results to return per URL/username |
| `proxy` | object | Optional | `{"useApifyProxy": true}` | Proxy configuration with optional residential groups |

### Example Input
```json
{
  "directUrls": ["https://www.instagram.com/p/DTA4-URETWb/"]
}
```

### Output
```json
{
  "inputUrl": "https://www.instagram.com/p/DTA4-URETWb/",
  "id": "3801288658474055067",
  "type": "Video",
  "shortCode": "DTA4-URETWb",
  "caption": "MLG edits are better than brain rot memes anyways. #meme #brainrot #trends #marketing",
  "hashtags": ["meme", "brainrot", "trends", "marketing"],
  "mentions": [],
  "url": "https://www.instagram.com/p/DTA4-URETWb/",
  "commentsCount": 548,
  "firstComment": "",
  "latestComments": [
    {
      "id": "18047392928704528",
      "text": "",
      "ownerUsername": "isackissokool",
      "timestamp": "2026-01-06T02:12:40.000Z",
      "repliesCount": 0,
      "likesCount": 0,
      "owner": {
        "id": "67983476425",
        "is_verified": false,
        "username": "isackissokool"
      }
    }
  ],
  "dimensionsHeight": 1920,
  "dimensionsWidth": 1080,
  "displayUrl": "https://scontent-mia3-1.cdninstagram.com/...",
  "videoUrl": "https://scontent-mia3-2.cdninstagram.com/...",
  "audioUrl": "https://scontent-mia5-1.cdninstagram.com/...",
  "likesCount": 18974,
  "videoViewCount": 131855,
  "videoPlayCount": 245464,
  "timestamp": "2026-01-02T15:51:22.000Z",
  "ownerFullName": "NoGood",
  "ownerUsername": "nogood.io",
  "ownerId": "8367974286",
  "productType": "clips",
  "videoDuration": 44.9,
  "musicInfo": {
    "artist_name": "nogood.io",
    "song_name": "Original audio",
    "uses_original_audio": true,
    "should_mute_audio": false,
    "audio_id": "25479239625103352"
  },
  "isCommentsDisabled": false,
  "transcript": "The Great Meme Reset has officially begun, but here's why it's doomed to fail. 2025 was dominated by AI-generated slot memes, and everyone's tired of them, which is why the Great Meme Reset was started..."
}
```

---

## 2. apify/instagram-scraper

**Actor ID:** `apify/instagram-scraper`

**Description:** Scrapes Instagram posts/reels from profiles or URLs with full engagement data, comments, and sponsor information.

**Source:** [Apify Instagram Scraper](https://apify.com/apify/instagram-scraper/input-schema)

### Available Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `directUrls` | array | Optional | — | Instagram URLs to scrape (profiles, posts, hashtags, places) |
| `resultsType` | string | Optional | `"posts"` | What to extract: `posts`, `comments`, `details`, `mentions`, `reels`, or `stories` |
| `resultsLimit` | integer | Optional | 200 | Max posts or comments (max 50 comments per post) per URL |
| `onlyPostsNewerThan` | string | Optional | — | Date filter in `YYYY-MM-DD` format or relative like `"1 days"` |
| `search` | string | Optional | — | Search query for profiles, hashtags, or places |
| `searchType` | string | Optional | `"hashtag"` | Search target: `user`, `hashtag`, or `place` |
| `searchLimit` | integer | Optional | 1 | Number of search results to return (max 250) |
| `addParentData` | boolean | Optional | `false` | Add source metadata to results (e.g., profile metadata for profile posts) |

### Example Input
```json
{
  "directUrls": ["https://www.instagram.com/wendys/"],
  "resultsLimit": 3
}
```

### Output
```json
{
  "id": "3784860661818747151",
  "type": "Video",
  "shortCode": "DSGhrgIDmkP",
  "caption": "Finals week had us all drained so I had to help wake students up with @wendys new sparkling energy drinks #wendyspartner",
  "hashtags": ["wendyspartner"],
  "mentions": ["wendys"],
  "url": "https://www.instagram.com/p/DSGhrgIDmkP/",
  "commentsCount": 63,
  "firstComment": "BRING BACK GHOST PEPPER RANCHHH",
  "latestComments": [
    {
      "id": "18070884722108551",
      "text": "BRING BACK GHOST PEPPER RANCHHH",
      "ownerUsername": "sarinroberts",
      "timestamp": "2025-12-24T04:02:50.000Z",
      "repliesCount": 0,
      "likesCount": 0,
      "owner": {
        "id": "68334344597",
        "is_verified": false,
        "username": "sarinroberts"
      }
    }
  ],
  "dimensionsHeight": 1918,
  "dimensionsWidth": 1080,
  "displayUrl": "https://instagram.flas1-1.fna.fbcdn.net/...",
  "videoUrl": "https://instagram.flas1-1.fna.fbcdn.net/...",
  "audioUrl": "https://instagram.flas1-2.fna.fbcdn.net/...",
  "likesCount": -1,
  "videoViewCount": 151277,
  "videoPlayCount": 2542022,
  "timestamp": "2025-12-10T23:51:23.000Z",
  "ownerUsername": "kylan_darnell",
  "ownerFullName": "Kylan Olivia Darnell",
  "ownerId": "417504118",
  "productType": "clips",
  "videoDuration": 37.3,
  "paidPartnership": true,
  "sponsors": [
    {
      "id": "20703145",
      "username": "wendys"
    }
  ],
  "taggedUsers": [
    {
      "full_name": "Wendy's",
      "id": "20703145",
      "is_verified": true,
      "username": "wendys"
    }
  ],
  "coauthorProducers": [
    {
      "id": "20703145",
      "is_verified": true,
      "username": "wendys"
    }
  ],
  "musicInfo": {
    "artist_name": "kylan_darnell",
    "song_name": "Original audio",
    "uses_original_audio": true,
    "audio_id": "25432230316463621"
  },
  "isCommentsDisabled": false,
  "inputUrl": "https://www.instagram.com/wendys/"
}
```

---

## 3. apify/website-content-crawler

**Actor ID:** `apify/website-content-crawler`

**Description:** Crawls websites and extracts content as markdown with full metadata including OpenGraph, JSON-LD, and headers.

**Source:** [Apify Website Content Crawler](https://apify.com/apify/website-content-crawler/input-schema)

### Available Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `startUrls` | array | **Yes** | — | Starting URLs for the crawl |
| `proxyConfiguration` | object | **Yes** | `{"useApifyProxy": true}` | Proxy settings for geo-targeting and anti-blocking |
| `crawlerType` | string | Optional | `"playwright:firefox"` | Engine: `playwright:adaptive`, `playwright:firefox`, `cheerio`, `jsdom`, `playwright:chrome` |
| `maxCrawlDepth` | integer | Optional | 20 | Maximum link depth to follow |
| `maxCrawlPages` | integer | Optional | 9999999 | Total page limit before termination |
| `includeUrlGlobs` | array | Optional | `[]` | Glob patterns for URLs to include |
| `excludeUrlGlobs` | array | Optional | `[]` | Glob patterns for URLs to exclude |
| `useSitemaps` | boolean | Optional | `false` | Discover URLs from sitemap files |
| `respectRobotsTxtFile` | boolean | Optional | `false` | Consult robots.txt before crawling |
| `maxConcurrency` | integer | Optional | 200 | Maximum parallel browser/client instances |
| `initialCookies` | array | Optional | `[]` | Pre-set cookies for all requests |
| `customHttpHeaders` | object | Optional | `{}` | Custom HTTP headers for requests |
| `waitForSelector` | string | Optional | `""` | CSS selector to wait for before processing |
| `dynamicContentWaitSecs` | integer | Optional | 10 | Max wait time for dynamic content |
| `maxScrollHeightPixels` | integer | Optional | 5000 | Maximum scroll distance |
| `removeElementsCssSelector` | string | Optional | `"nav, footer, script, ..."` | Elements to remove before extraction |
| `removeCookieWarnings` | boolean | Optional | `true` | Remove cookie consent dialogs |
| `htmlTransformer` | string | Optional | `"readableText"` | Algorithm: `readableText`, `extractus`, `defuddle`, `none` |
| `saveMarkdown` | boolean | Optional | `true` | Convert HTML to markdown |
| `saveHtml` | boolean | Optional | `false` | Store transformed HTML |
| `saveFiles` | boolean | Optional | `false` | Download linked PDF, DOC, XLS, CSV files |
| `saveScreenshots` | boolean | Optional | `false` | Capture screenshots (Firefox only) |
| `maxResults` | integer | Optional | 9999999 | Maximum stored results |
| `maxRequestRetries` | integer | Optional | 3 | Retry attempts for network errors |
| `requestTimeoutSecs` | integer | Optional | 60 | Timeout per request (1-600) |
| `keepUrlFragments` | boolean | Optional | `false` | Treat URL fragments as separate pages |
| `ignoreCanonicalUrl` | boolean | Optional | `false` | Use actual URLs instead of canonical |
| `expandIframes` | boolean | Optional | `true` | Extract content from iframes |
| `blockMedia` | boolean | Optional | `false` | Block images, fonts, stylesheets in browser mode |
| `debugMode` | boolean | Optional | `false` | Store debug output and HTML files |

### Example Input
```json
{
  "startUrls": [{ "url": "https://nogood.io/blog/" }],
  "maxCrawlPages": 1
}
```

### Output
```json
{
  "url": "https://nogood.io/blog/",
  "crawl": {
    "loadedUrl": "https://nogood.io/blog/",
    "loadedTime": "2026-01-07T19:52:32.145Z",
    "referrerUrl": "https://nogood.io/blog/",
    "depth": 0,
    "httpStatusCode": 200
  },
  "metadata": {
    "canonicalUrl": "https://nogood.io/blog/",
    "title": "Growth Marketing Insights, Updates, & Trends | NoGood",
    "description": "Everything you need to know about growth marketing! Get the latest insights, updates, and trends with our growth marketing content.",
    "author": null,
    "keywords": null,
    "languageCode": "en-US",
    "openGraph": [
      { "property": "og:locale", "content": "en_US" },
      { "property": "og:type", "content": "article" },
      { "property": "og:title", "content": "Growth Marketing Insights, Updates, & Trends | NoGood" },
      { "property": "og:description", "content": "Everything you need to know about growth marketing..." },
      { "property": "og:url", "content": "https://nogood.io/blog/" },
      { "property": "og:site_name", "content": "NoGood: Growth Marketing Agency" },
      { "property": "og:image", "content": "https://nogood.io/wp-content/uploads/2024/06/OG_IMAGE_1200x630.jpg" },
      { "property": "og:image:width", "content": "2400" },
      { "property": "og:image:height", "content": "1260" },
      { "property": "og:image:type", "content": "image/jpeg" }
    ],
    "jsonLd": [
      {
        "@context": "https://schema.org",
        "@graph": [
          {
            "@type": ["WebPage", "CollectionPage"],
            "@id": "https://nogood.io/blog/",
            "url": "https://nogood.io/blog/",
            "name": "Growth Marketing Insights, Updates, & Trends | NoGood",
            "datePublished": "2021-03-17T13:58:16+00:00",
            "dateModified": "2025-10-07T16:48:19+00:00",
            "inLanguage": "en-US"
          },
          {
            "@type": "Organization",
            "@id": "https://nogood.io/#organization",
            "name": "NoGood",
            "url": "https://nogood.io/"
          }
        ]
      }
    ],
    "headers": {
      "content-type": "text/html; charset=UTF-8",
      "x-powered-by": "WP Engine",
      "cache-control": "max-age=600, must-revalidate"
    }
  },
  "text": "Growth Marketing Insights, Updates, & Trends\nStay ahead of the growth curve\nFeatured growth bites...",
  "markdown": "# Growth Marketing Insights, Updates, & Trends\n\n## Stay ahead of the growth curve\n\n## Featured growth bites\n\n## All articles"
}
```

---

## 4. apimaestro/linkedin-company-posts

**Actor ID:** `apimaestro/linkedin-company-posts`

**Description:** Scrapes LinkedIn company posts with engagement stats, media, and author information. No login/cookies required.

**Source:** [Apify LinkedIn Company Posts Scraper](https://apify.com/apimaestro/linkedin-company-posts/input-schema)

### Available Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `company_name` | string | **Yes** | `"google"` | Company name or URL (e.g., `"google"` or `"linkedin.com/company/google"`) |
| `page_number` | integer | Optional | 1 | Page number for pagination (min: 1) |
| `limit` | integer | Optional | 100 | Result limit per request (1-100) |
| `sort` | string | Optional | `"recent"` | Sort order: `"recent"` or `"top"` |

### Example Input
```json
{
  "company_name": "nogood",
  "limit": 3,
  "sort": "recent"
}
```

### Output
```json
{
  "activity_urn": "7414742659166302209",
  "full_urn": "urn:li:activity:7414742659166302209",
  "post_url": "https://www.linkedin.com/posts/nogood_nearly-60-of-people-use-ai-tools-to-influence-activity-7414742659166302209-zPYC",
  "text": "Nearly 60% of people use AI tools to influence their purchasing decisions.\n\nThat's why maintaining brand visibility is more important than ever for organic success.\n\nJoin NoGood's CEO, Mostafa ElBermawy, January 12th at 12PM EST for a FREE lightning course on how to build your AI search strategy beyond SEO.\n\nLearn how to make your brand visible in ChatGPT, Perplexity, and Google's AI Overviews before your competitors do.\n\nSign up here: https://lnkd.in/eMK_H8wk\n\nPS: Stay tuned for more details about our in-depth, 2-day course at the end of January.",
  "posted_at": {
    "relative": "49m",
    "is_edited": false,
    "date": "2026-01-07 20:00:09",
    "timestamp": 1767812409202
  },
  "post_language_code": "en",
  "post_type": "regular",
  "author": {
    "name": "NoGood",
    "follower_count": 77160,
    "company_url": "https://www.linkedin.com/company/nogood/posts",
    "logo_url": "https://media.licdn.com/dms/image/v2/D4E0BAQET3qbeiGOC3A/company-logo_400_400/..."
  },
  "stats": {
    "total_reactions": 2,
    "like": 1,
    "love": 1
  },
  "media": {
    "type": "image",
    "items": [
      {
        "url": "https://media.licdn.com/dms/image/v2/D4E22AQEPKSlNd54QVw/feedshare-shrink_1280/...",
        "width": 1200,
        "height": 628
      }
    ]
  },
  "document": null,
  "source_company": "nogood"
}
```

---

## 5. clockworks/tiktok-scraper

**Actor ID:** `clockworks/tiktok-scraper`

**Description:** Scrapes TikTok videos with author info, engagement metrics, hashtags, and subtitle links.

**Source:** [Apify TikTok Scraper](https://apify.com/clockworks/tiktok-scraper/input-schema)

### Available Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `hashtags` | array | Optional | — | TikTok hashtags to scrape videos from |
| `profiles` | array | Optional | — | TikTok usernames to scrape |
| `postURLs` | array | Optional | — | Direct TikTok video URLs to scrape |
| `searchQueries` | array | Optional | — | Keywords to search for videos/profiles |
| `resultsPerPage` | integer | Optional | 1 | Videos per hashtag/profile/search (1-1,000,000) |
| `profileScrapeSections` | array | Optional | `["videos"]` | Profile sections: `"videos"` or `"reposts"` |
| `profileSorting` | string | Optional | `"latest"` | Order: `"latest"`, `"popular"`, or `"oldest"` |
| `excludePinnedPosts` | boolean | Optional | `false` | Exclude pinned posts from results |
| `oldestPostDateUnified` | string | Optional | — | Only scrape posts after this date |
| `newestPostDate` | string | Optional | — | Only scrape posts before this date |
| `mostDiggs` | integer | Optional | — | Filter: videos with hearts < this number |
| `leastDiggs` | integer | Optional | — | Filter: videos with hearts >= this number |
| `maxFollowersPerProfile` | integer | Optional | 0 | Max follower profiles to scrape per input |
| `maxFollowingPerProfile` | integer | Optional | 0 | Max following profiles to scrape per input |
| `searchSection` | string | Optional | `""` | Search within: `"Top"`, `"Video"`, or `"Profile"` |
| `maxProfilesPerQuery` | integer | Optional | 10 | Profiles to return per search query |
| `searchSorting` | string | Optional | `"0"` | Sort: `"Most relevant"`, `"Most liked"`, or `"Latest"` |
| `searchDatePosted` | string | Optional | `"0"` | Date range filter for search |
| `scrapeRelatedVideos` | boolean | Optional | `false` | Extract related videos from post URLs |
| `shouldDownloadVideos` | boolean | Optional | `false` | Download TikTok videos (charged add-on) |
| `shouldDownloadCovers` | boolean | Optional | `false` | Download video thumbnails |
| `shouldDownloadSubtitles` | boolean | Optional | `false` | Download video subtitles |
| `shouldDownloadSlideshowImages` | boolean | Optional | `false` | Download slideshow images |
| `shouldDownloadAvatars` | boolean | Optional | `false` | Download author profile pictures |
| `shouldDownloadMusicCovers` | boolean | Optional | `false` | Download sound cover images |
| `videoKvStoreIdOrName` | string | Optional | — | Named Key-Value Store for media |
| `commentsPerPost` | integer | Optional | 0 | Max comments to extract per video |
| `maxRepliesPerComment` | integer | Optional | 0 | Max replies per comment |
| `proxyCountryCode` | string | Optional | `"None"` | Country proxy for location-specific scraping |

### Example Input
```json
{
  "profiles": ["nogood.io"],
  "resultsPerPage": 3
}
```

### Output
```json
{
  "id": "7592641437091532062",
  "text": "Pinterest would never right? #pinterest #openai #brandstrategy #marketing",
  "textLanguage": "en",
  "createTime": 1767799606,
  "createTimeISO": "2026-01-07T15:26:46.000Z",
  "isAd": false,
  "authorMeta": {
    "id": "6776371925083915270",
    "name": "nogood.io",
    "profileUrl": "https://www.tiktok.com/@nogood.io",
    "nickName": "NoGood",
    "verified": false,
    "signature": "growth marketing agency committed to the bit",
    "bioLink": "Linktr.ee/NoGood.io",
    "avatar": "https://p16-common-sign.tiktokcdn-us.com/...",
    "commerceUserInfo": {
      "commerceUser": true,
      "category": "Shopping & Retail"
    },
    "privateAccount": false,
    "following": 49,
    "friends": 19,
    "fans": 190000,
    "heart": 7800000,
    "video": 1451
  },
  "musicMeta": {
    "musicName": "original sound",
    "musicAuthor": "NoGood",
    "musicOriginal": true,
    "musicId": "7592641367957981982"
  },
  "webVideoUrl": "https://www.tiktok.com/@nogood.io/video/7592641437091532062",
  "videoMeta": {
    "height": 1280,
    "width": 720,
    "duration": 73,
    "coverUrl": "https://p16-common-sign.tiktokcdn-eu.com/...",
    "definition": "720p",
    "format": "mp4",
    "subtitleLinks": [
      {
        "language": "eng-US",
        "downloadLink": "https://v16-webapp.tiktokcdn-eu.com/...",
        "source": "ASR",
        "sourceUnabbreviated": "automatic speech recognition"
      }
    ]
  },
  "diggCount": 23,
  "shareCount": 0,
  "playCount": 295,
  "collectCount": 0,
  "commentCount": 0,
  "repostCount": 0,
  "mentions": [],
  "hashtags": [
    { "name": "pinterest" },
    { "name": "openai" },
    { "name": "brandstrategy" },
    { "name": "marketing" }
  ],
  "isSlideshow": false,
  "isPinned": false,
  "isSponsored": false,
  "input": "nogood.io",
  "fromProfileSection": "videos"
}
```

---

## 6. clockworks/tiktok-trends-scraper

**Actor ID:** `clockworks/tiktok-trends-scraper`

**Description:** Scrapes TikTok Trend Discovery data including trending hashtags, songs, creators, and videos filtered by region, time period, and industry.

**Source:** [Apify TikTok Trends Scraper](https://apify.com/clockworks/tiktok-trends-scraper)

### Available Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `country` | string | Optional | `"US"` | ISO 3166-1 alpha-2 country code (e.g., "US", "GB", "DE") |
| `period` | string | Optional | `"7"` | Time range: `"7"` (7 days), `"30"` (30 days), `"120"` (120 days) |
| `dataType` | string | Optional | `"hashtag"` | What to scrape: `"hashtag"`, `"song"`, `"creator"`, `"video"` |
| `industry` | string | Optional | — | Industry filter (e.g., "Technology", "Beauty & Personal Care") |
| `maxResults` | integer | Optional | 30 | Maximum results to return |

### Example Input
```json
{
  "country": "US",
  "period": "7",
  "dataType": "hashtag",
  "industry": "Technology",
  "maxResults": 30
}
```

### Output
```json
{
  "hashtag": "aimarketing",
  "hashtagUrl": "https://www.tiktok.com/tag/aimarketing",
  "totalViews": 1250000000,
  "totalVideos": 85000,
  "trendingScore": 95,
  "growthRate": "+42%",
  "relatedHashtags": ["marketing", "ai", "digitalmarketing", "socialmedia"],
  "topCreators": [
    {
      "username": "marketingtips",
      "followers": 2500000
    }
  ],
  "industry": "Technology",
  "region": "US",
  "scrapedAt": "2026-01-22T10:30:00.000Z"
}
```

**Kairo Usage:** This scraper discovers WHAT is trending on TikTok. Kairo uses TWO recipes with **CHAINED EXECUTION**:

1. **TT-TRENDS-GENERAL** - Broad US trends without industry filter (20 results)
   - Captures viral content any brand could potentially ride
   - Think: major cultural moments, viral sounds, trending formats

2. **TT-TRENDS-INDUSTRY** - Industry-specific trends (15 results)
   - Uses LLM-inferred industry from brand context
   - Captures trends specifically relevant to the brand's market

**Phase 3 Chained Pipeline (TT-TRENDS → TT-1):**
```
┌──────────────────────────────────────────────────────────────┐
│  PARALLEL EXECUTION (Phase 1)                                │
│  ┌─────────┐ ┌─────────┐ ┌───────┐ ┌───────┐ ┌────────────┐ │
│  │  IG-1   │ │  IG-3   │ │ YT-1  │ │ LI-1  │ │ TT-TRENDS  │ │
│  └─────────┘ └─────────┘ └───────┘ └───────┘ └──────┬─────┘ │
│                                                      │       │
│                                                      ▼       │
│                                         Extract top hashtags │
│                                                      │       │
│  SEQUENTIAL (Phase 2)                                ▼       │
│                                              ┌─────────────┐ │
│                                              │    TT-1     │ │
│                                              │ (transcripts)│ │
│                                              └─────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

The chained pipeline:
1. TT-TRENDS-GENERAL and TT-TRENDS-INDUSTRY run in parallel (discover what's trending)
2. Top trending hashtags are extracted and ranked by `trendingScore` and `growthRate`
3. TT-1 runs with these hashtags to get actual video content WITH transcripts
4. Result: Rich, transcript-laden content for what's actually trending on TikTok

This ensures opportunity synthesis has both:
- Knowledge of WHAT is trending (from TT-TRENDS)
- Rich transcript content for HOW to create similar content (from TT-1)

**Valid Industry Categories:**
- Technology, Apparel & Accessories, Beauty & Personal Care
- Food & Beverage, Sports & Outdoors, Financial Services
- Education, Games, Travel, E-commerce
- Vehicles & Transportation, Life Services, News & Entertainment

---

## 7. streamers/youtube-scraper

**Actor ID:** `streamers/youtube-scraper`

**Description:** Scrapes YouTube videos and channel data with full metadata, engagement stats, and channel information.

**Source:** [Apify YouTube Scraper](https://apify.com/streamers/youtube-scraper/input-schema)

### Available Input Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `startUrls` | array | Optional | `[]` | YouTube video, channel, playlist, hashtag, or search URLs |
| `searchQueries` | array | Optional | `["Crawlee"]` | Search terms (like YouTube search bar) |
| `maxResults` | integer | Optional | 0 | Limit regular videos per search term (0-999,999) |
| `maxResultsShorts` | integer | Optional | 0 | Limit short-form videos per search term |
| `maxResultStreams` | integer | Optional | 0 | Limit livestream videos per search term |
| `downloadSubtitles` | boolean | Optional | `false` | Extract and convert subtitles to SRT |
| `saveSubsToKVS` | boolean | Optional | `false` | Store subtitles in key-value store |
| `subtitlesLanguage` | string | Optional | `"en"` | Language: `any`, `en`, `de`, `es`, `fr`, `it`, `ja`, `ko`, `nl`, `pt`, `ru` |
| `preferAutoGeneratedSubtitles` | boolean | Optional | `false` | Prefer auto-generated over user subtitles |
| `subtitlesFormat` | string | Optional | `"srt"` | Format: `srt`, `vtt`, `xml`, `plaintext` |
| `sortingOrder` | string | Optional | — | Sort: `relevance`, `rating`, `date`, `views` |
| `dateFilter` | string | Optional | — | Upload time: `hour`, `today`, `week`, `month`, `year` |
| `videoType` | string | Optional | — | Type: `video` or `movie` |
| `lengthFilter` | string | Optional | — | Duration: `under4`, `between420`, `plus20` |
| `isHD` | boolean | Optional | — | Filter HD videos only |
| `hasSubtitles` | boolean | Optional | — | Filter videos with subtitles |
| `hasCC` | boolean | Optional | — | Filter videos with closed captions |
| `is3D` | boolean | Optional | — | Filter 3D videos |
| `isLive` | boolean | Optional | — | Filter live videos |
| `is4K` | boolean | Optional | — | Filter 4K videos |
| `is360` | boolean | Optional | — | Filter 360° videos |
| `isHDR` | boolean | Optional | — | Filter HDR videos |
| `isVR180` | boolean | Optional | — | Filter VR180 videos |
| `hasLocation` | boolean | Optional | — | Filter videos with location |
| `oldestPostDate` | string | Optional | — | Only posts after this date (absolute or relative like `"1 day"`) |
| `sortVideosBy` | string | Optional | — | Channel sort: `NEWEST`, `POPULAR`, `OLDEST` |

### Example Input
```json
{
  "startUrls": [{ "url": "https://www.youtube.com/channel/UCZ4qs1SgV7wTkM2VjHByuRQ" }],
  "maxResults": 3
}
```

### Output
```json
{
  "title": "Culture & Creativity: You Are Not Who You Think You Are | SXSW London 2025",
  "translatedTitle": null,
  "type": "video",
  "id": "8eEOaCCxGwo",
  "url": "https://www.youtube.com/watch?v=8eEOaCCxGwo",
  "thumbnailUrl": "https://i.ytimg.com/vi/8eEOaCCxGwo/maxresdefault.jpg",
  "viewCount": 316,
  "date": "2025-06-16T20:09:39.000Z",
  "likes": 2,
  "location": null,
  "channelName": "NoGood",
  "channelUrl": "https://www.youtube.com/channel/UCZ4qs1SgV7wTkM2VjHByuRQ",
  "channelUsername": "NoGoodHQ",
  "channelId": "UCZ4qs1SgV7wTkM2VjHByuRQ",
  "channelDescription": "Your daily dose of marketing knowledge & hot-takes",
  "channelJoinedDate": "Nov 1, 2018",
  "channelDescriptionLinks": [
    { "text": "Website", "url": "nogood.io" },
    { "text": "LinkedIn", "url": "https://www.linkedin.com/company/nogood/" },
    { "text": "Instagram", "url": "https://www.instagram.com/nogood.io/" },
    { "text": "TikTok", "url": "https://www.tiktok.com/@nogood.io" },
    { "text": "Linktree", "url": "https://linktr.ee/NoGood.io" }
  ],
  "channelLocation": "United States",
  "channelAvatarUrl": "https://yt3.googleusercontent.com/...",
  "channelBannerUrl": "https://yt3.googleusercontent.com/...",
  "channelTotalVideos": 542,
  "channelTotalViews": 132435511,
  "numberOfSubscribers": 86400,
  "isChannelVerified": false,
  "isAgeRestricted": false,
  "duration": "00:27:11",
  "commentsCount": 4,
  "text": "AI search is changing how brands are seen and discovered. And if you are not optimizing for AI chatbots with answer engine optimization, all of your marketing efforts will be for not.\n\nAt SXSW London 2025, Jim McKelvey - Co-Founder @ Block, Mostafa ElBermawy - Founder & CEO of Goodie AI and NoGood, and Marina Chilingaryan - Director of Social & Community @ NoGood discuss this new future of branding.",
  "hashtags": [],
  "isMembersOnly": false,
  "isPaidContent": false,
  "commentsTurnedOff": false,
  "fromChannelListPage": "videos"
}
```

---

## Summary Table

| Actor Name | Platform | Key Data Points |
|------------|----------|-----------------|
| `apify/instagram-reel-scraper` | Instagram | Video/Reel details, comments, transcript, engagement |
| `apify/instagram-scraper` | Instagram | Posts/Reels, comments, sponsors, tagged users |
| `apify/website-content-crawler` | Web | Page content as markdown, metadata, OpenGraph, JSON-LD |
| `apimaestro/linkedin-company-posts` | LinkedIn | Company posts, engagement stats, media |
| `clockworks/tiktok-scraper` | TikTok | Videos, author info, hashtags, subtitles |
| `clockworks/tiktok-trends-scraper` | TikTok | Trending hashtags, songs, creators by region/industry |
| `streamers/youtube-scraper` | YouTube | Videos, channel info, engagement, description |
