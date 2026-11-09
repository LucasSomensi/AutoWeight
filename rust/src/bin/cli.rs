fn main() {
    if let Err(error) = autoweight::entry(true) {
        eprintln!("AutoWeight: {error}");
        std::process::exit(1);
    }
}
