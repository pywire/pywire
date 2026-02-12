use pyo3::prelude::*;
use std::collections::HashMap;
use tree_sitter::{Node, Parser};

#[pyclass]
#[derive(Clone)]
pub struct ParsedDirective {
    #[pyo3(get)]
    pub name: String,
    #[pyo3(get)]
    pub content: Option<String>,
    #[pyo3(get)]
    pub line: usize,
    #[pyo3(get)]
    pub column: usize,
}

#[pyclass]
pub struct ParsedNode {
    #[pyo3(get)]
    pub tag: Option<String>,
    #[pyo3(get)]
    pub is_block: bool,
    #[pyo3(get)]
    pub block_keyword: Option<String>,
    #[pyo3(get)]
    pub text_content: Option<String>,
    #[pyo3(get)]
    pub expression: Option<String>,
    #[pyo3(get)]
    pub attributes: HashMap<String, Option<String>>,
    #[pyo3(get)]
    pub children: Vec<Py<ParsedNode>>,
    #[pyo3(get)]
    pub line: usize,
    #[pyo3(get)]
    pub column: usize,
    #[pyo3(get)]
    pub is_raw: bool,
}

#[pyclass]
pub struct ParsedDocument {
    #[pyo3(get)]
    pub directives: Vec<ParsedDirective>,
    #[pyo3(get)]
    pub python_code: String,
    #[pyo3(get)]
    pub template: Vec<Py<ParsedNode>>,
}

#[pyfunction]
fn version() -> &'static str {
    "0.2.0-unified-v2"
}

#[pyfunction]
fn parse(py: Python<'_>, source: String) -> PyResult<ParsedDocument> {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_pywire::language() as _)
        .map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!(
                "Failed to set language: {}",
                e
            ))
        })?;

    let tree = parser.parse(&source, None).ok_or_else(|| {
        PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Failed to parse source")
    })?;

    let root = tree.root_node();
    let mut directives: Vec<ParsedDirective> = Vec::new();
    let mut python_code = String::new();
    let mut template = Vec::new();

    let count = root.child_count();

    for i in 0..count {
        let child = root.child(i).unwrap();
        let kind = child.kind();

        match kind {
            "directives_section" => {
                let mut cursor = child.walk();
                for d_node in child.children(&mut cursor) {
                    directives.push(map_any_directive(&source, d_node));
                }
            }
            "frontmatter" => {
                if let Some(content_node) = child.child_by_field_name("python_content") {
                    python_code.push_str(&get_node_text(&source, content_node));
                } else {
                    // Also check for anonymous children if field name isn't set (it should be)
                    for j in 0..child.child_count() {
                        let inner = child.child(j).unwrap();
                        if inner.kind() == "python_content" {
                            python_code.push_str(&get_node_text(&source, inner));
                        }
                    }
                }
            }
            "template_section" => {
                let mut cursor = child.walk();
                for t_node in child.children(&mut cursor) {
                    // Filter out any punctuation or whitespace that tree-sitter might expose
                    match t_node.kind() {
                        "tag" | "self_closing_tag" | "void_tag" | "script_tag" | "style_tag"
                        | "text" | "interpolation" | "brace_block" | "end_brace_block"
                        | "doctype" | "hyphen" | "bang" => {
                            let mapped = map_node(py, &source, t_node)?;
                            template.push(Py::new(py, mapped)?);
                        }
                        _ => {}
                    }
                }
            }
            _ => {}
        }
    }

    Ok(ParsedDocument {
        directives,
        python_code,
        template,
    })
}

fn get_node_text(source: &str, node: Node) -> String {
    source[node.start_byte()..node.end_byte()].to_string()
}

fn map_any_directive(source: &str, node: Node) -> ParsedDirective {
    let text = get_node_text(source, node);
    let trimmed = text.trim();

    // name starts after '!' and ends at first non-word char
    let name_part_full = if let Some(stripped) = trimmed.strip_prefix('!') {
        stripped
    } else {
        trimmed
    };

    let name_end = name_part_full
        .find(|c: char| !c.is_alphanumeric() && c != '_')
        .unwrap_or(name_part_full.len());
    let name_part = &name_part_full[..name_end];

    // content is everything after the name
    let content_part = name_part_full[name_end..].trim();
    let content = if content_part.is_empty() {
        None
    } else {
        Some(content_part.to_string())
    };

    let start_point = node.start_position();

    ParsedDirective {
        name: name_part.to_string(),
        content,
        line: start_point.row + 1,
        column: start_point.column,
    }
}

fn map_node(py: Python<'_>, source: &str, node: Node) -> PyResult<ParsedNode> {
    let mut tag = None;
    let mut is_block = false;
    let mut block_keyword = None;
    let mut text_content = None;
    let mut expression = None;
    let mut attributes = HashMap::new();
    let mut children = Vec::new();

    let start_point = node.start_position();
    let line = start_point.row + 1;
    let column = start_point.column;

    let is_raw = false;

    let kind = node.kind();

    match kind {
        "tag" | "self_closing_tag" | "void_tag" | "script_tag" | "style_tag" => {
            if let Some(name_node) = node.child_by_field_name("name") {
                tag = Some(get_node_text(source, name_node));
            } else if let Some(start_node) = node.child_by_field_name("start_tag") {
                let text = get_node_text(source, start_node);
                tag = text.strip_prefix('<').map(|s| s.to_string());
            } else if node.kind() == "script_tag" {
                tag = Some("script".to_string());
            } else if node.kind() == "style_tag" {
                tag = Some("style".to_string());
            }

            let mut is_raw_tag = false;
            if node.kind() == "script_tag" || node.kind() == "style_tag" {
                is_raw_tag = true;
                let mut start_byte = 0;
                let mut end_byte = 0;
                let mut found_start = false;

                let mut cursor = node.walk();
                for child in node.children(&mut cursor) {
                    let k = child.kind();
                    if k == ">" {
                        start_byte = child.end_byte();
                        found_start = true;
                    } else if k == "</script>" || k == "</style>" {
                        end_byte = child.start_byte();
                    }
                }

                if found_start && end_byte >= start_byte {
                    let raw_text = source[start_byte..end_byte].to_string();
                    if !raw_text.is_empty() {
                        let text_node = ParsedNode {
                            tag: None,
                            is_block: false,
                            block_keyword: None,
                            text_content: Some(raw_text),
                            expression: None,
                            attributes: HashMap::new(),
                            children: Vec::new(),
                            line,
                            column,
                            is_raw: true,
                        };
                        children.push(Py::new(py, text_node)?);
                    }
                }
            }

            let mut cursor = node.walk();
            for child in node.children(&mut cursor) {
                let kind = child.kind();
                if kind == "attribute" {
                    let mut is_shorthand = false;

                    let mut cursor_logic = child.walk();
                    for attr_child in child.children(&mut cursor_logic) {
                        let k = attr_child.kind();
                        if k == "attribute_shorthand" {
                            let text = get_node_text(source, attr_child);
                            // text is "{name}"
                            let inner = text[1..text.len() - 1].trim().to_string();

                            // Check if it's actually a spread that got parsed as shorthand
                            if text.starts_with("{**") {
                                attributes.insert("__pywire_spread__".to_string(), Some(text));
                            } else {
                                attributes.insert(format!("__pw_sh_{}", inner), Some(text));
                            }
                            is_shorthand = true;
                            break;
                        } else if k == "spread_shorthand" {
                            let text = get_node_text(source, attr_child);
                            // text is "{**expr}"
                            attributes.insert("__pywire_spread__".to_string(), Some(text));
                            is_shorthand = true;
                            break;
                        }
                    }

                    if !is_shorthand {
                        let mut attr_name = String::new();
                        let mut attr_value = None;
                        if let Some(n) = child.child_by_field_name("name") {
                            attr_name = get_node_text(source, n);
                        }
                        if let Some(v) = child.child_by_field_name("value") {
                            let text = get_node_text(source, v);
                            if (text.starts_with('"') && text.ends_with('"'))
                                || (text.starts_with('\'') && text.ends_with('\''))
                            {
                                attr_value = Some(text[1..text.len() - 1].to_string());
                            } else {
                                attr_value = Some(text);
                            }
                        }
                        attributes.insert(attr_name, attr_value);
                    }
                } else if !is_raw_tag {
                    match kind {
                        "tag" | "self_closing_tag" | "void_tag" | "script_tag" | "style_tag"
                        | "text" | "interpolation" | "brace_block" | "end_brace_block"
                        | "ERROR" | "hyphen" | "bang" | "comment" => {
                            let mapped = map_node(py, source, child)?;
                            children.push(Py::new(py, mapped)?);
                        }
                        _ => {}
                    }
                }
            }
        }
        "brace_block" => {
            is_block = true;
            // brace_block is now a single token: "{$keyword expr}"
            // Parse the text to extract keyword and expression
            let text = get_node_text(source, node);
            // Strip {$ prefix and } suffix
            let inner = text.trim_start_matches("{$").trim_end_matches('}');

            // Find the keyword (first word)
            let keywords = [
                "if", "for", "try", "await", "elif", "else", "finally", "except", "then", "catch",
                "html",
            ];
            for kw in keywords {
                if let Some(stripped) = inner.strip_prefix(kw) {
                    block_keyword = Some(kw.to_string());
                    let rest = stripped.trim();
                    if !rest.is_empty() {
                        expression = Some(rest.to_string());
                    }
                    break;
                }
            }
        }
        "end_brace_block" => {
            is_block = true;
            // end_brace_block is now a single token: "{/keyword}"
            let text = get_node_text(source, node);
            let inner = text.trim_start_matches("{/").trim_end_matches('}');
            block_keyword = Some(format!("/{}", inner));
        }
        "interpolation" => {
            is_block = true;
            block_keyword = Some("interpolation".to_string());
            if let Some(expr_node) = node.child_by_field_name("expr") {
                expression = Some(get_node_text(source, expr_node));
            }
        }
        "text" | "python_line" | "hyphen" | "bang" => {
            text_content = Some(get_node_text(source, node));
        }
        "ERROR" => {
            text_content = Some(get_node_text(source, node));
        }
        _ => {}
    }

    Ok(ParsedNode {
        tag,
        is_block,
        block_keyword,
        text_content,
        expression,
        attributes,
        children,
        line,
        column,
        is_raw,
    })
}

#[pymodule]
fn _pywire_parser(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ParsedDirective>()?;
    m.add_class::<ParsedNode>()?;
    m.add_class::<ParsedDocument>()?;
    m.add_function(wrap_pyfunction!(parse, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    Ok(())
}
