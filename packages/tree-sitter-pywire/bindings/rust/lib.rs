use tree_sitter::Language;

#[link(name = "tree-sitter-pywire", kind = "static")]
extern "C" {
    fn tree_sitter_pywire() -> *const ();
}

/// Get the tree-sitter [Language] for this grammar.
pub fn language() -> Language {
    unsafe { Language::from_raw(tree_sitter_pywire() as _) }
}

/// The content of the [`node-types.json`] file for this grammar.
pub const NODE_TYPES: &str = include_str!("../../src/node-types.json");

/// The queries of this grammar.
pub const QUERIES: &str = include_str!("../../queries/highlights.scm");

#[cfg(test)]
mod tests {
    use tree_sitter::Parser;

    #[test]
    fn test_can_load_grammar() {
        let mut parser = Parser::new();
        parser
            .set_language(&super::language())
            .expect("Error loading PyWire grammar");

        let source = "!path \"/test\"\n---html---\n<div></div>";
        let tree = parser.parse(source, None).unwrap();
        let root = tree.root_node();

        println!("Tree: {}", root.to_sexp());
        assert_eq!(root.kind(), "source_file");

        let mut _directive_found = false;
        let mut _separator_found = false;

        // Traverse tree to find nodes
        let mut cursor = root.walk();
        for child in root.children(&mut cursor) {
            println!("Child: {}", child.kind());
            if child.kind() == "directives_section" {
                let mut dc = child.walk();
                for d in child.children(&mut dc) {
                    if d.kind() == "directive" {
                        _directive_found = true;
                    }
                }
            }
            if child.kind() == "separator" {
                // frontmatter separator
                _separator_found = true;
            }
            // check template section for separators too if implicit
        }

        // Simple check
        assert!(
            root.to_sexp().contains("directive"),
            "Directive not found in S-expression"
        );
    }
}
