// gen_indent_template.js
// Run: node gen_indent_template.js
// Output: asset/Indent.docx  (overwrites existing template)

const {
    Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
    ImageRun, AlignmentType, BorderStyle, WidthType, ShadingType,
    VerticalAlign, Header, Footer, PageNumber
} = require("docx");

const fs = require("fs");
const path = require("path");

// ── helpers ─────────────────────────────────────────────────────────────────

const THIN = { style: BorderStyle.SINGLE, size: 4,  color: "000000" };
const THICK = { style: BorderStyle.SINGLE, size: 8,  color: "000000" };
const NONE  = { style: BorderStyle.NONE,   size: 0,  color: "FFFFFF" };

function allBorders(b) {
    return { top: b, bottom: b, left: b, right: b };
}

function cell(text, opts = {}) {
    const {
        bold     = false,
        size     = 18,
        italic   = false,
        align    = AlignmentType.LEFT,
        shade    = null,
        borders  = allBorders(THIN),
        colSpan  = 1,
        vAlign   = VerticalAlign.CENTER,
        width    = null,
        font     = "Arial",
    } = opts;

    const cellProps = {
        borders,
        verticalAlign: vAlign,
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        children: [
            new Paragraph({
                alignment: align,
                children: [
                    new TextRun({ text, bold, size, italics: italic, font })
                ]
            })
        ]
    };

    if (shade) cellProps.shading = { fill: shade, type: ShadingType.CLEAR };
    if (colSpan > 1) cellProps.columnSpan = colSpan;
    if (width)  cellProps.width = width;

    return new TableCell(cellProps);
}

function labelCell(text, w) {
    return cell(text, {
        bold: true, size: 18, shade: "E8E8E8",
        borders: allBorders(THIN),
        width: { size: w, type: WidthType.DXA }
    });
}

function valueCell(text, w) {
    return cell(text, {
        bold: false, size: 18,
        borders: allBorders(THIN),
        width: { size: w, type: WidthType.DXA }
    });
}

// ── logo ─────────────────────────────────────────────────────────────────────

const logoPath = path.join(__dirname, "Indent_unpacked", "word", "media", "image1.jpeg");
let logoRun = null;
if (fs.existsSync(logoPath)) {
    logoRun = new ImageRun({
        type: "jpeg",
        data: fs.readFileSync(logoPath),
        transformation: { width: 130, height: 50 },
        altText: { title: "Logo", description: "Company Logo", name: "Logo" }
    });
}

// ── document ─────────────────────────────────────────────────────────────────

// Page: A4  (11906 x 16838 DXA),  margins 720 DXA = 0.5 inch
// Content width = 11906 - 720 - 720 = 10466 DXA

const CONTENT_W = 10466;

// ── 1. Company banner ─────────────────────────────────────────────────────────
//    Logo left  |  INDENT  center  |  website right

const bannerRow = new TableRow({
    children: [
        new TableCell({
            borders: allBorders(NONE),
            width: { size: 3000, type: WidthType.DXA },
            verticalAlign: VerticalAlign.CENTER,
            margins: { top: 40, bottom: 40, left: 80, right: 80 },
            children: [
                new Paragraph({
                    alignment: AlignmentType.LEFT,
                    children: logoRun ? [logoRun] : [new TextRun({ text: "DISHAANHITECH", bold: true, size: 24, font: "Arial" })]
                })
            ]
        }),
        new TableCell({
            borders: allBorders(NONE),
            width: { size: 4466, type: WidthType.DXA },
            verticalAlign: VerticalAlign.CENTER,
            margins: { top: 40, bottom: 40, left: 80, right: 80 },
            children: [
                new Paragraph({
                    alignment: AlignmentType.CENTER,
                    children: [new TextRun({ text: "INDENT", bold: true, size: 40, font: "Arial" })]
                })
            ]
        }),
        new TableCell({
            borders: allBorders(NONE),
            width: { size: 3000, type: WidthType.DXA },
            verticalAlign: VerticalAlign.CENTER,
            margins: { top: 40, bottom: 40, left: 80, right: 80 },
            children: [
                new Paragraph({
                    alignment: AlignmentType.RIGHT,
                    children: [new TextRun({ text: "www.dishaanhitech.com", size: 16, font: "Arial", color: "2E75B6" })]
                })
            ]
        }),
    ]
});

const bannerTable = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [3000, 4466, 3000],
    borders: { top: NONE, bottom: NONE, left: NONE, right: NONE, insideH: NONE, insideV: NONE },
    rows: [bannerRow]
});

// ── 2. Divider line ───────────────────────────────────────────────────────────

const divider = new Paragraph({
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: "1F3864" } },
    spacing: { before: 80, after: 80 },
    children: []
});

// ── 3. Info header table ──────────────────────────────────────────────────────
//  4-column grid:  Label | Value | Label | Value

const L = 1500;  // label width
const V = 3733;  // value width  (L+V)*2 = 10466

const infoTable = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [L, V, L, V],
    rows: [
        new TableRow({ children: [
            labelCell("Site Code",      L), valueCell("{{site_code}}",      V),
            labelCell("Indent No",      L), valueCell("{{indent_no}}",      V),
        ]}),
        new TableRow({ children: [
            labelCell("Project Name",   L), valueCell("{{project_name}}",   V),
            labelCell("Indent Date",    L), valueCell("{{indent_date}}",    V),
        ]}),
        new TableRow({ children: [
            labelCell("Customer Name",  L), valueCell("{{customer_name}}",  V),
            labelCell("Required Date",  L), valueCell("{{required_date}}",  V),
        ]}),
        new TableRow({ children: [
            labelCell("Sale Order No",  L), valueCell("{{sale_order_no}}",  V),
            labelCell("Indent Category",L), valueCell("{{indent_category}}",V),
        ]}),
    ]
});

// ── 4. Items table ────────────────────────────────────────────────────────────
//  Columns: SL No | Item Code | Item Name | Specification | Unit | Qty | Location

const COL_W = [600, 1200, 2000, 2266, 700, 700, 1500];  // sum = 8966 ... but let me adjust
// sum must = CONTENT_W (10466)
// let's redistribute: 600+1200+2200+2600+700+700+1466 = hmm let me do properly
// 600 + 1200 + 2100 + 2400 + 700 + 700 + 2766 = 10466  ✓
const COLS = [600, 1200, 2100, 2400, 700, 700, 2766];

function headerCell(text) {
    return new TableCell({
        borders: allBorders(THICK),
        shading: { fill: "1F3864", type: ShadingType.CLEAR },
        verticalAlign: VerticalAlign.CENTER,
        margins: { top: 80, bottom: 80, left: 100, right: 100 },
        children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [new TextRun({ text, bold: true, size: 18, color: "FFFFFF", font: "Arial" })]
        })]
    });
}

function dataCell(text, w, align = AlignmentType.CENTER) {
    return new TableCell({
        borders: allBorders(THIN),
        verticalAlign: VerticalAlign.CENTER,
        margins: { top: 60, bottom: 60, left: 100, right: 100 },
        width: { size: w, type: WidthType.DXA },
        children: [new Paragraph({
            alignment: align,
            children: [new TextRun({ text, size: 18, font: "Arial" })]
        })]
    });
}

const itemsHeaderRow = new TableRow({
    tableHeader: true,
    children: [
        headerCell("Sl\nNo"),
        headerCell("Item Code"),
        headerCell("Item Name"),
        headerCell("Specification"),
        headerCell("Unit"),
        headerCell("Qty"),
        headerCell("Location"),
    ]
});

// No template row — items rows are added programmatically via python-docx
// after docxtpl renders the header/signature sections.
const itemsTable = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: COLS,
    rows: [itemsHeaderRow]
});

// ── 5. Signature block ────────────────────────────────────────────────────────

const SIG_L = 1800;
const SIG_V = CONTENT_W / 2 - SIG_L;   // ~3433

function sigRow(label, nameTag, dateTag) {
    return new TableRow({
        children: [
            labelCell(label,                          SIG_L),
            valueCell(`${nameTag}  [${dateTag}]`,    SIG_V),
            new TableCell({ borders: allBorders(NONE), width: { size: 20, type: WidthType.DXA }, children: [new Paragraph({ children: [] })] }),
            new TableCell({ borders: allBorders(NONE), width: { size: SIG_L - 20, type: WidthType.DXA }, children: [new Paragraph({ children: [] })] }),
            new TableCell({ borders: allBorders(NONE), width: { size: SIG_V,      type: WidthType.DXA }, children: [new Paragraph({ children: [] })] }),
        ]
    });
}

// Signature table:  left half = fields, right half = blank (for stamp/seal)
const SIG_HALF = Math.floor(CONTENT_W / 2);

const sigTable = new Table({
    width: { size: CONTENT_W, type: WidthType.DXA },
    columnWidths: [SIG_L, SIG_HALF - SIG_L, 40, SIG_L - 40, CONTENT_W - SIG_HALF],
    rows: [
        new TableRow({ children: [
            labelCell("Indent Placed By",              SIG_L),
            valueCell("{{indent_placed_by}}",          SIG_HALF - SIG_L),
            new TableCell({ borders: allBorders(NONE), columnSpan: 3, width: { size: CONTENT_W - SIG_HALF, type: WidthType.DXA },
                children: [new Paragraph({ children: [] })] })
        ]}),
        new TableRow({ children: [
            labelCell("Created By",                    SIG_L),
            valueCell("{{created_by}}  [{{created_at}}]",  SIG_HALF - SIG_L),
            new TableCell({ borders: allBorders(NONE), columnSpan: 3, width: { size: CONTENT_W - SIG_HALF, type: WidthType.DXA },
                children: [new Paragraph({ children: [] })] })
        ]}),
        new TableRow({ children: [
            labelCell("Verified By",                   SIG_L),
            valueCell("{{verified_by}}  [{{verified_at}}]", SIG_HALF - SIG_L),
            new TableCell({ borders: allBorders(NONE), columnSpan: 3, width: { size: CONTENT_W - SIG_HALF, type: WidthType.DXA },
                children: [new Paragraph({ children: [] })] })
        ]}),
        new TableRow({ children: [
            labelCell("Approved By",                   SIG_L),
            valueCell("{{approved_by}}  [{{approved_at}}]", SIG_HALF - SIG_L),
            new TableCell({ borders: allBorders(NONE), columnSpan: 3, width: { size: CONTENT_W - SIG_HALF, type: WidthType.DXA },
                children: [new Paragraph({ children: [] })] })
        ]}),
    ]
});

// ── Build document ────────────────────────────────────────────────────────────

const doc = new Document({
    sections: [{
        properties: {
            page: {
                size:   { width: 11906, height: 16838 },   // A4
                margin: { top: 720, bottom: 720, left: 720, right: 720 }
            }
        },
        children: [
            bannerTable,
            divider,
            new Paragraph({ spacing: { before: 80, after: 0 }, children: [] }),
            infoTable,
            new Paragraph({ spacing: { before: 120, after: 0 }, children: [] }),
            itemsTable,
            new Paragraph({ spacing: { before: 120, after: 0 }, children: [] }),
            sigTable,
        ]
    }]
});

Packer.toBuffer(doc).then(buffer => {
    const out = path.join(__dirname, "Indent.docx");
    fs.writeFileSync(out, buffer);
    console.log("✅  Saved:", out);
}).catch(e => {
    console.error("❌  Error:", e.message);
});
