fn main() {
    let src_dir = std::path::Path::new("src");

    let mut config = cc::Build::new();
    config.include(src_dir);

    // macOS BSD ar exits 0 when passed the 'D' (deterministic) flag but prints a
    // warning. cc crate sees exit 0 and keeps using cqD. Work around this by writing
    // a thin wrapper to OUT_DIR that strips 'D' from the operation argument.
    #[cfg(target_os = "macos")]
    {
        use std::os::unix::fs::PermissionsExt;
        let out_dir = std::env::var("OUT_DIR").unwrap();
        let wrapper = format!("{}/ar-wrapper", out_dir);
        std::fs::write(
            &wrapper,
            "#!/bin/sh\nop=$(echo \"$1\" | tr -d 'D')\nshift\nexec /usr/bin/ar \"$op\" \"$@\"\n",
        )
        .unwrap();
        std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o755)).unwrap();
        config.archiver(wrapper.as_str());
    }

    config
        .warnings(false)
        .std("c11")
        .file(src_dir.join("parser.c"))
        .compile("tree-sitter-pywire");
}
