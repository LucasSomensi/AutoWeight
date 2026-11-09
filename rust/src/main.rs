#![cfg_attr(windows, windows_subsystem = "windows")]
fn main() {
    #[cfg(windows)]
    {
        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn AttachConsole(id: u32) -> i32;
        }
        // Attach only when explicitly using terminal functions; double-click opens only the GUI.
        if std::env::args().skip(1).any(|a| {
            matches!(
                a.as_str(),
                "--sem-gui" | "--help" | "-h" | "--version" | "-V" | "rele"
            )
        }) {
            unsafe {
                AttachConsole(u32::MAX);
            }
        }
    }
    if let Err(error) = autoweight::entry(false) {
        eprintln!("AutoWeight: {error}");
        std::process::exit(1);
    }
}
