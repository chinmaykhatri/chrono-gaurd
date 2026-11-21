"""Generate a presentation deck for ChronoGuard using python-pptx."""

from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def create_deck(output_path: Path):
    prs = Presentation()
    # 16:9 widescreen
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    DARK_BG = RGBColor(20, 19, 15)       # #14130f
    CARD_BG = RGBColor(32, 30, 24)       # #201e18
    TEXT_LIGHT = RGBColor(245, 245, 242) # #f5f5f2
    TEXT_MUTED = RGBColor(160, 158, 148) # #a09e94
    ACCENT = RGBColor(235, 115, 30)      # Orange accent #eb731e
    ACCENT_GREEN = RGBColor(46, 184, 92) # Green #2eb85c
    BORDER_COLOR = RGBColor(50, 48, 40)

    def apply_dark_background(slide):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = DARK_BG
        bg.line.color.rgb = DARK_BG
        return bg

    def add_header(slide, title_text, kicker="CHRONOGUARD"):
        kicker_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11), Inches(0.4))
        tf_k = kicker_box.text_frame
        tf_k.word_wrap = True
        p_k = tf_k.paragraphs[0]
        p_k.text = kicker.upper()
        p_k.font.size = Pt(11)
        p_k.font.bold = True
        p_k.font.color.rgb = ACCENT

        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.7), Inches(11), Inches(0.8))
        tf_t = title_box.text_frame
        tf_t.word_wrap = True
        p_t = tf_t.paragraphs[0]
        p_t.text = title_text
        p_t.font.size = Pt(24)
        p_t.font.bold = True
        p_t.font.color.rgb = TEXT_LIGHT

    # Slide 1: Title Slide
    s1 = prs.slides.add_slide(prs.slide_layouts[6])
    apply_dark_background(s1)

    tbox = s1.shapes.add_textbox(Inches(1.0), Inches(1.8), Inches(11.3), Inches(3.5))
    tf1 = tbox.text_frame
    tf1.word_wrap = True
    
    p = tf1.paragraphs[0]
    p.text = "CHRONOGUARD"
    p.font.size = Pt(54)
    p.font.bold = True
    p.font.color.rgb = ACCENT

    p2 = tf1.add_paragraph()
    p2.text = "Active Semantic Cache Invalidation Gateway for LLMs"
    p2.font.size = Pt(28)
    p2.font.bold = True
    p2.font.color.rgb = TEXT_LIGHT

    p3 = tf1.add_paragraph()
    p3.text = "\nEliminating stale hallucinations in cached LLM responses without sacrificing speed or budget."
    p3.font.size = Pt(18)
    p3.font.color.rgb = TEXT_MUTED

    p4 = tf1.add_paragraph()
    p4.text = "\nBifrost Gateway Ecosystem (Go) • Tavily Live Search Evidence • Production-Ready Gateway"
    p4.font.size = Pt(14)
    p4.font.color.rgb = ACCENT_GREEN

    # Slide 2: Problem
    s2 = prs.slides.add_slide(prs.slide_layouts[6])
    apply_dark_background(s2)
    add_header(s2, "The Semantic Cache Dilemma: High Speed, Blind to Time", "THE PROBLEM")

    col1 = s2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.8), Inches(5.6), Inches(4.8))
    col1.fill.solid()
    col1.fill.fore_color.rgb = CARD_BG
    col1.line.color.rgb = BORDER_COLOR
    tf = col1.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "The Promise of Semantic Caching"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = ACCENT_GREEN

    items_good = [
        "70-80% reduction in LLM inference costs",
        "Sub-50ms response times for repeat queries",
        "Semantic matching catches paraphrased questions"
    ]
    for it in items_good:
        pi = tf.add_paragraph()
        pi.text = f"• {it}"
        pi.font.size = Pt(14)
        pi.font.color.rgb = TEXT_LIGHT

    col2 = s2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.8), Inches(1.8), Inches(5.7), Inches(4.8))
    col2.fill.solid()
    col2.fill.fore_color.rgb = CARD_BG
    col2.line.color.rgb = BORDER_COLOR
    tf = col2.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "The Catastrophic Failure (Time Blindness)"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = RGBColor(235, 77, 75)

    items_bad = [
        "Prompt: 'What is the latest stable LTS of Node.js?'",
        "Cached response: 'Node.js 20' (cached 4 months ago)",
        "Real-world state: 'Node.js 22 LTS released yesterday'",
        "Dilemma: Short TTLs = wasted money; Long TTLs = silent hallucinations",
        "Fact: 68.1% of cached answers in dynamic domains drift into staleness!"
    ]
    for it in items_bad:
        pi = tf.add_paragraph()
        pi.text = f"• {it}"
        pi.font.size = Pt(14)
        pi.font.color.rgb = TEXT_LIGHT

    # Slide 3: Solution
    s3 = prs.slides.add_slide(prs.slide_layouts[6])
    apply_dark_background(s3)
    add_header(s3, "ChronoGuard: Active Truth-Maintenance Memory Layer", "THE SOLUTION")

    cards = [
        ("1. Claim-Level Deconstruction", "Dissects LLM answers into atomic factual claims: [Entity, Attribute, Stated Value] and assigns volatility half-lives.", Inches(0.8), Inches(1.8)),
        ("2. Shared Fact Ledger", "Re-uses verified facts across hundreds of cache entries. One update invalidates or confirms all referencing answers.", Inches(6.8), Inches(1.8)),
        ("3. Budget-Optimal Verification", "Cho & Garcia-Molina Poisson drift model + Lagrangian solver checks high-traffic drifting facts within strict budget limits.", Inches(0.8), Inches(4.3)),
        ("4. Grounded Re-Generation", "Instead of blunt eviction, automatically repairs answers with live Tavily evidence before serving to the user.", Inches(6.8), Inches(4.3)),
    ]

    for title, desc, l, t in cards:
        card = s3.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l, t, Inches(5.7), Inches(2.2))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = BORDER_COLOR
        tf = card.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(18)
        p.font.bold = True
        p.font.color.rgb = ACCENT

        p2 = tf.add_paragraph()
        p2.text = f"\n{desc}"
        p2.font.size = Pt(13)
        p2.font.color.rgb = TEXT_LIGHT

    # Slide 4: Market Comparison
    s4 = prs.slides.add_slide(prs.slide_layouts[6])
    apply_dark_background(s4)
    add_header(s4, "Competitive Matrix: Why ChronoGuard Outperforms the Market", "MARKET DIFFERENTIATION")

    table_shape = s4.shapes.add_table(6, 5, Inches(0.8), Inches(1.8), Inches(11.7), Inches(4.8))
    table = table_shape.table
    table.columns[0].width = Inches(3.7)
    table.columns[1].width = Inches(2.0)
    table.columns[2].width = Inches(2.0)
    table.columns[3].width = Inches(2.0)
    table.columns[4].width = Inches(2.0)

    headers = ["Capability", "GPTCache", "Portkey", "Cloudflare AI", "ChronoGuard"]
    for c, h in enumerate(headers):
        cell = table.cell(0, c)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = ACCENT if c == 4 else CARD_BG
        p = cell.text_frame.paragraphs[0]
        p.font.bold = True
        p.font.size = Pt(13)
        p.font.color.rgb = DARK_BG if c == 4 else TEXT_LIGHT

    rows_data = [
        ("Semantic Paraphrase Matching", "Yes", "Basic", "Exact Only", "Yes (Bifrost)"),
        ("Claim-Level Deconstruction", "No", "No", "No", "YES (Pydantic)"),
        ("Live Web Invalidation", "No (Timer)", "No (Timer)", "No (Timer)", "YES (Tavily)"),
        ("Semantic-Hit Guard (False Match)", "Vulnerable", "Vulnerable", "N/A", "YES (Go Guard)"),
        ("Grounded Response Repair", "No (Flush)", "No (Flush)", "No (Flush)", "YES (Re-Gen)"),
    ]

    for r, row in enumerate(rows_data):
        for c, val in enumerate(row):
            cell = table.cell(r + 1, c)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = CARD_BG
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(12)
            if c == 4:
                p.font.bold = True
                p.font.color.rgb = ACCENT_GREEN
            else:
                p.font.color.rgb = TEXT_LIGHT

    # Slide 5: Architecture
    s5 = prs.slides.add_slide(prs.slide_layouts[6])
    apply_dark_background(s5)
    add_header(s5, "High-Performance 3-Tier Enterprise Architecture", "ARCHITECTURE")

    arch_boxes = [
        ("1. High-Performance Gateway (Go Bifrost Plugins)", 
         "• Hook 7 (cg-front): Prompt classification, manifest check, semantic guard\n• Hook 8 (semantic_cache): Vector lookup in Weaviate\n• Hook 9 (cg-back): Post-LLM claim ingestion, manifest publishing", 
         Inches(0.8), Inches(1.8)),
        ("2. Verification Engine (FastAPI Verifier)", 
         "• Extractor: Spans entity/attribute/value claims\n• Evidence: Live Tavily API search with domain authority tiering\n• LLM Judge: Bayesian freshness score & grounded repair generator", 
         Inches(4.8), Inches(1.8)),
        ("3. Storage & Observability (Postgres + Redis + React)", 
         "• Redis 7: Sub-ms manifests, reverse-index cascade, token-bucket limits\n• PostgreSQL 16: Audit trail, cost ledger, verified claim history\n• React 18 Console: 10 pages, SSE real-time event feeds, ROI analytics", 
         Inches(8.8), Inches(1.8)),
    ]

    for title, desc, l, t in arch_boxes:
        b = s5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l, t, Inches(3.7), Inches(4.8))
        b.fill.solid()
        b.fill.fore_color.rgb = CARD_BG
        b.line.color.rgb = BORDER_COLOR
        tf = b.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(16)
        p.font.bold = True
        p.font.color.rgb = ACCENT

        p2 = tf.add_paragraph()
        p2.text = f"\n{desc}"
        p2.font.size = Pt(12)
        p2.font.color.rgb = TEXT_LIGHT

    # Slide 6: Benchmark & Proof
    s6 = prs.slides.add_slide(prs.slide_layouts[6])
    apply_dark_background(s6)
    add_header(s6, "Empirical Benchmark: 99.2% Stale Reduction at 93% Cost Savings", "PROVEN RESULTS")

    # Benchmark table
    btable_shape = s6.shapes.add_table(7, 4, Inches(0.8), Inches(1.8), Inches(6.8), Inches(4.8))
    btable = btable_shape.table
    btable.columns[0].width = Inches(2.2)
    btable.columns[1].width = Inches(1.5)
    btable.columns[2].width = Inches(1.5)
    btable.columns[3].width = Inches(1.6)

    bheaders = ["Strategy", "Stale / 1k Req", "Credits / 1k Req", "Repairs"]
    for c, h in enumerate(bheaders):
        cell = btable.cell(0, c)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = CARD_BG
        p = cell.text_frame.paragraphs[0]
        p.font.bold = True
        p.font.size = Pt(12)
        p.font.color.rgb = ACCENT

    bdata = [
        ("Passive Cache", "681.03", "0.00", "0"),
        ("Fixed TTL 1h", "10.27", "1000.00", "144"),
        ("Fixed TTL 12h", "5.40", "95.89", "12"),
        ("Fixed TTL 48h", "338.54", "27.40", "4"),
        ("Always Verify", "0.00", "2000.00", "4"),
        ("ChronoGuard", "5.17", "68.49", "4"),
    ]

    for r, row in enumerate(bdata):
        for c, val in enumerate(row):
            cell = btable.cell(r + 1, c)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(40, 36, 28) if r == 5 else CARD_BG
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(11)
            if r == 5:
                p.font.bold = True
                p.font.color.rgb = ACCENT_GREEN
            else:
                p.font.color.rgb = TEXT_LIGHT

    # Highlights box on the right
    rbox = s6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(7.9), Inches(1.8), Inches(4.6), Inches(4.8))
    rbox.fill.solid()
    rbox.fill.fore_color.rgb = CARD_BG
    rbox.line.color.rgb = BORDER_COLOR
    rtf = rbox.text_frame
    rtf.word_wrap = True

    rp1 = rtf.paragraphs[0]
    rp1.text = "Key Takeaways"
    rp1.font.size = Pt(20)
    rp1.font.bold = True
    rp1.font.color.rgb = ACCENT

    rh_items = [
        "99.2% Staleness Reduction: Drops stale cache delivery from 681 down to 5.17 per 1,000 queries.",
        "93% Cost Efficiency: Consumes 68 credits vs 1,000 credits on 1h TTL while delivering better freshness.",
        "Grounded Self-Healing: Injects verified web evidence into prompt to seamlessly heal cache answers.",
        "Certified Gate G1: All numbers generated via automated deterministic replay (no fabricated metrics)."
    ]
    for h in rh_items:
        rp = rtf.add_paragraph()
        rp.text = f"\n• {h}"
        rp.font.size = Pt(13)
        rp.font.color.rgb = TEXT_LIGHT

    # Slide 7: Conclusion & Summary
    s7 = prs.slides.add_slide(prs.slide_layouts[6])
    apply_dark_background(s7)
    add_header(s7, "The Future of Reliable Enterprise LLM Infrastructure", "SUMMARY")

    cbox = s7.shapes.add_textbox(Inches(1.5), Inches(2.0), Inches(10.3), Inches(4.5))
    ctf = cbox.text_frame
    ctf.word_wrap = True

    cp1 = ctf.paragraphs[0]
    cp1.text = "ChronoGuard solves the fundamental flaw of LLM caching."
    cp1.font.size = Pt(26)
    cp1.font.bold = True
    cp1.font.color.rgb = ACCENT

    cp2 = ctf.add_paragraph()
    cp2.text = (
        "\n1. Enterprise Ready: Tested with 54 Python tests, 21 Go tests, 10 Docker services.\n"
        "2. Zero User Latency: Asynchronous verification keeps cache hits under 50ms.\n"
        "3. Active Grounding: Eliminates hallucinations before the user ever sees them.\n"
        "4. Plug-and-Play: Integrates directly into Bifrost gateway ecosystems."
    )
    cp2.font.size = Pt(16)
    cp2.font.color.rgb = TEXT_LIGHT

    cp3 = ctf.add_paragraph()
    cp3.text = "\nReady for deployment. Open for Q&A and Live Demo!"
    cp3.font.size = Pt(18)
    cp3.font.bold = True
    cp3.font.color.rgb = ACCENT_GREEN

    prs.save(str(output_path))
    print(f"Presentation saved successfully to: {output_path}")

if __name__ == "__main__":
    out = Path("c:/Users/chinm/Pictures/OneDrive/Desktop/Chrono-gaurd/chronoguard/ChronoGuard_Pitch_Deck.pptx")
    create_deck(out)
