use tree_sitter::Parser;

fn main() {
    let mut parser = Parser::new();
    parser
        .set_language(&tree_sitter_pywire::language() as _)
        .unwrap();
    let source = "---html---\n<button>Inc</button>";
    let tree = parser.parse(source, None).unwrap();
    let root = tree.root_node();
    println!("Root kind: {}", root.kind());
    println!("Child count: {}", root.child_count());
    for i in 0..root.child_count() {
        let child = root.child(i).unwrap();
        println!(
            "Child {}: {} - '{}'",
            i,
            child.kind(),
            &source[child.start_byte()..child.end_byte()]
        );
    }
}
