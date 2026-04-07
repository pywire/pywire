fn main() {
    let src_dir = std::path::Path::new("src");

    let mut config = cc::Build::new();
    config.include(src_dir);
    config
        .std("c11")
        .file(src_dir.join("parser.c"))
        .compile("tree-sitter-pywire");
}
