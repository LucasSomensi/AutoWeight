use crate::{
    config::Config,
    photos::{self, Record},
    runtime::{Runtime, State},
};
use eframe::egui::{self, Color32, RichText, TextureHandle};
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};

struct Panel {
    runtime: Option<Runtime>,
    state: State,
    data: PathBuf,
    records: Vec<Record>,
    selected: Option<PathBuf>,
    texture: Option<TextureHandle>,
    notice: String,
    last_scan: Instant,
    closing: bool,
    demo: bool,
    smoke: Option<Instant>,
    preview_hover: PreviewHover,
    live_texture: Option<TextureHandle>,
    live_frame: Option<Instant>,
}
#[derive(Default)]
struct PreviewHover {
    since: Option<Instant>,
}
impl PreviewHover {
    fn visible(&mut self, hovered: bool, now: Instant) -> bool {
        if !hovered {
            self.since = None;
            return false;
        }
        now.saturating_duration_since(*self.since.get_or_insert(now)) >= Duration::from_secs(2)
    }
}
pub fn run(
    root: PathBuf,
    config: anyhow::Result<Config>,
    verbose: bool,
    demo: bool,
    smoke: bool,
) -> anyhow::Result<()> {
    let mut state = State::default();
    let runtime = if demo {
        state.weight = Some(28500);
        state.received = Some(Instant::now());
        state.camera = true;
        state.message = "Demonstração — hardware e rede desativados.".into();
        None
    } else {
        match config.and_then(|c| Runtime::start(c, verbose)) {
            Ok(r) => Some(r),
            Err(e) => {
                state.message = format!("Não foi possível iniciar: {e}");
                None
            }
        }
    };
    let icon = image::load_from_memory(include_bytes!("../../assets/robot.png"))
        .ok()
        .map(|im| {
            let im = im.to_rgba8();
            egui::IconData {
                width: im.width(),
                height: im.height(),
                rgba: im.into_raw(),
            }
        });
    let mut viewport = egui::ViewportBuilder::default()
        .with_inner_size([1100., 800.])
        .with_min_inner_size([760., 600.]);
    if let Some(icon) = icon {
        viewport = viewport.with_icon(icon);
    }
    let options = eframe::NativeOptions {
        viewport,
        ..Default::default()
    };
    eframe::run_native(
        "AutoWeight • Sala da balança",
        options,
        Box::new(move |cc| {
            cc.egui_ctx.set_visuals(egui::Visuals::light());
            let mut panel = Panel {
                runtime,
                state,
                data: root.join("AutoWeightData"),
                records: Vec::new(),
                selected: None,
                texture: None,
                notice: String::new(),
                last_scan: Instant::now() - Duration::from_secs(2),
                closing: false,
                demo,
                smoke: smoke.then(Instant::now),
                preview_hover: PreviewHover::default(),
                live_texture: None,
                live_frame: None,
            };
            panel.refresh(&cc.egui_ctx);
            Ok(Box::new(panel))
        }),
    )
    .map_err(|e| anyhow::anyhow!("Falha ao abrir interface gráfica: {e}"))
}

impl Panel {
    fn camera_status(&mut self, ui: &mut egui::Ui) {
        let response = ui.label(
            RichText::new(if self.state.camera {
                "Câmera conectada"
            } else {
                "Sem imagem recente"
            })
            .size(22.)
            .color(if self.state.camera {
                Color32::from_rgb(40, 117, 80)
            } else {
                Color32::from_rgb(180, 35, 24)
            }),
        );
        if !self.preview_hover.visible(
            response.hovered() && self.state.camera && !self.closing,
            Instant::now(),
        ) {
            self.live_texture = None;
            self.live_frame = None;
            return;
        }
        let current = self.runtime.as_ref().and_then(|r| {
            r.frame
                .lock()
                .unwrap()
                .as_ref()
                .filter(|(time, _)| {
                    time.elapsed() <= Duration::from_secs(2) && Some(*time) != self.live_frame
                })
                .cloned()
        });
        if let Some((time, bytes)) = current
            && let Ok(image) = image::load_from_memory(&bytes)
        {
            let image = image.thumbnail(960, 540).to_rgba8();
            let color = egui::ColorImage::from_rgba_unmultiplied(
                [image.width() as usize, image.height() as usize],
                image.as_raw(),
            );
            if let Some(texture) = &mut self.live_texture {
                texture.set(color, egui::TextureOptions::LINEAR);
            } else {
                self.live_texture = Some(ui.ctx().load_texture(
                    "camera-ao-vivo",
                    color,
                    egui::TextureOptions::LINEAR,
                ));
            }
            self.live_frame = Some(time);
        }
        let fresh = self
            .live_frame
            .is_some_and(|time| time.elapsed() <= Duration::from_secs(2));
        let mut tooltip = egui::Tooltip::for_widget(&response);
        tooltip.popup = tooltip.popup.width(520.);
        tooltip.show(|ui| {
            ui.strong("Câmera ao vivo");
            if fresh && let Some(texture) = &self.live_texture {
                ui.add(egui::Image::new(texture).max_width(500.));
            } else {
                ui.label(if self.demo {
                    "Prévia indisponível no modo de demonstração."
                } else {
                    "Aguardando imagem recente da câmera…"
                });
            }
        });
    }
    fn refresh(&mut self, ctx: &egui::Context) {
        let follow = self
            .records
            .last()
            .is_none_or(|r| Some(&r.path) == self.selected.as_ref());
        match photos::list(&self.data) {
            Ok(records) => {
                let missing = self
                    .selected
                    .as_ref()
                    .is_none_or(|p| !records.iter().any(|r| &r.path == p));
                self.records = records;
                if follow || missing {
                    let new = self.records.last().map(|r| r.path.clone());
                    if self.selected != new {
                        self.selected = new;
                        self.load(ctx);
                    }
                }
                if self.records.is_empty() {
                    self.selected = None;
                    self.texture = None;
                }
            }
            Err(_) => {
                self.notice = "Não foi possível consultar os registros anteriores.".into();
            }
        }
        self.last_scan = Instant::now();
    }
    fn load(&mut self, ctx: &egui::Context) {
        self.texture = None;
        let Some(path) = &self.selected else {
            return;
        };
        let result = (|| -> anyhow::Result<(egui::ColorImage, bool, bool)> {
            let bytes = std::fs::read(path)?;
            let contingency = photos::contingency(&bytes);
            let image = image::load_from_memory(&bytes)?.to_rgba8();
            let white = image.pixels().all(|p| p.0[..3] == [255, 255, 255]);
            let color = egui::ColorImage::from_rgba_unmultiplied(
                [image.width() as usize, image.height() as usize],
                image.as_raw(),
            );
            Ok((color, contingency, white))
        })();
        match result {
            Ok((image, contingency, white)) => {
                self.texture =
                    Some(ctx.load_texture("pesagem", image, egui::TextureOptions::LINEAR));
                self.notice = if contingency {
                    "Ilustração de contingência — câmera indisponível."
                } else if white {
                    "Imagem branca de contingência — câmera indisponível."
                } else {
                    "Foto salva com sucesso."
                }
                .into();
            }
            Err(_) => self.notice = "Não foi possível abrir a foto registrada.".into(),
        }
    }
    fn navigate(&mut self, delta: isize, ctx: &egui::Context) {
        self.refresh(ctx);
        if let Some(index) = self
            .records
            .iter()
            .position(|r| Some(&r.path) == self.selected.as_ref())
        {
            let next = index as isize + delta;
            if next >= 0 && (next as usize) < self.records.len() {
                self.selected = Some(self.records[next as usize].path.clone());
                self.load(ctx);
            }
        }
    }
}
impl eframe::App for Panel {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        ctx.request_repaint_after(Duration::from_millis(200));
        if let Some(runtime) = &self.runtime {
            self.state = runtime.state.lock().unwrap().clone();
        }
        if self.last_scan.elapsed() > Duration::from_secs(1) {
            self.refresh(&ctx);
        }
        if self
            .smoke
            .is_some_and(|s| s.elapsed() > Duration::from_secs(3))
        {
            ctx.send_viewport_cmd(egui::ViewportCommand::Close);
        }
        if (ctx.input(|i| i.viewport().close_requested()) || self.closing)
            && let Some(r) = &self.runtime
        {
            r.stop.stop();
            if !r.finished() {
                ctx.send_viewport_cmd(egui::ViewportCommand::CancelClose);
                self.closing = true;
            } else {
                ctx.send_viewport_cmd(egui::ViewportCommand::Close);
            }
        }
        egui::CentralPanel::default()
            .frame(
                egui::Frame::new()
                    .fill(Color32::from_rgb(238, 242, 246))
                    .inner_margin(20.),
            )
            .show(ui, |ui| {
                egui::Frame::new()
                    .fill(Color32::from_rgb(21, 43, 64))
                    .inner_margin(24.)
                    .show(ui, |ui| {
                        ui.set_min_width(ui.available_width());
                        ui.label(
                            RichText::new("AutoWeight")
                                .size(30.)
                                .strong()
                                .color(Color32::WHITE),
                        );
                        ui.label(
                            RichText::new("MONITORAMENTO DE PESAGEM")
                                .color(Color32::from_rgb(169, 192, 212)),
                        );
                        ui.add_space(10.);
                        let button = egui::Button::new(
                            RichText::new(format!(
                                "Modo ausente: {}",
                                if self.state.away {
                                    "ATIVADO"
                                } else {
                                    "DESATIVADO"
                                }
                            ))
                            .strong()
                            .color(if self.state.away {
                                Color32::WHITE
                            } else {
                                Color32::from_rgb(36, 59, 80)
                            }),
                        )
                        .fill(if self.state.away {
                            Color32::from_rgb(40, 117, 80)
                        } else {
                            Color32::from_rgb(229, 235, 240)
                        });
                        if ui.add_enabled(!self.closing, button).clicked() {
                            if let Some(r) = &self.runtime {
                                r.toggle();
                            } else if self.demo {
                                self.state.away = !self.state.away;
                            }
                        }
                        let busy=self.runtime.as_ref().is_some_and(|r|r.siren.busy());
                        if ui.add_enabled(!self.closing && self.runtime.is_some() && !busy,
                            egui::Button::new(if busy {"Sirene em acionamento…"}else{"Testar sirene"}))
                            .on_hover_text("Aciona a sirene por 5 segundos, independentemente do modo ausente.")
                            .clicked() && let Some(runtime)=&self.runtime {
                                runtime.siren.test();
                        }
                    });
                ui.add_space(16.);
                ui.columns(2, |columns| {
                    columns[0].label("PESO ATUAL DA BALANÇA");
                    let recent = self.demo
                        || self
                            .state
                            .received
                            .is_some_and(|t| t.elapsed() <= Duration::from_secs(3));
                    columns[0].label(
                        RichText::new(format!(
                            "{} kg",
                            format_weight(if recent { self.state.weight } else { None })
                        ))
                        .size(48.)
                        .strong(),
                    );
                    columns[0].label(if recent {
                        "Recebendo dados"
                    } else {
                        "Sem leitura recente da balança"
                    });
                    columns[1].label("CÂMERA");
                    self.camera_status(&mut columns[1]);
                });
                ui.add_space(16.);
                ui.separator();
                ui.horizontal(|ui| {
                    ui.strong("FOTOS REGISTRADAS");
                    let index = self
                        .records
                        .iter()
                        .position(|r| Some(&r.path) == self.selected.as_ref());
                    if ui
                        .add_enabled(
                            index.is_some_and(|i| i > 0),
                            egui::Button::new("< Anterior"),
                        )
                        .clicked()
                    {
                        self.navigate(-1, &ctx);
                    }
                    ui.label(format!(
                        "{} / {}",
                        index.map_or(0, |i| i + 1),
                        self.records.len()
                    ));
                    if ui
                        .add_enabled(
                            index.is_some_and(|i| i + 1 < self.records.len()),
                            egui::Button::new("Próxima >"),
                        )
                        .clicked()
                    {
                        self.navigate(1, &ctx);
                    }
                    if ui
                        .add_enabled(self.texture.is_some(), egui::Button::new("Ampliar"))
                        .clicked()
                        && let Some(path) = &self.selected
                        && open_photo(path).is_err()
                    {
                        self.notice = "Não foi possível abrir o visualizador de imagens.".into();
                    }
                });
                if let Some(record) = self
                    .records
                    .iter()
                    .find(|r| Some(&r.path) == self.selected.as_ref())
                {
                    ui.label(
                        RichText::new(format!(
                            "{}   •   {} kg",
                            record.time.format("%d/%m/%Y às %H:%M:%S"),
                            format_weight(Some(record.weight))
                        ))
                        .size(22.)
                        .strong(),
                    );
                } else {
                    ui.heading("Nenhuma pesagem registrada");
                }
                ui.label(&self.notice);
                ui.label(if self.closing {
                    "Encerrando conexões…"
                } else {
                    &self.state.message
                });
                ui.label(&self.state.api);
                ui.label(&self.state.siren);
                let available = ui.available_size();
                if let Some(texture) = &self.texture {
                    ui.allocate_ui_with_layout(
                        available,
                        egui::Layout::top_down(egui::Align::Center),
                        |ui| {
                            ui.add(
                                egui::Image::new(texture).fit_to_exact_size(
                                    texture.size_vec2()
                                        * (available.x / texture.size_vec2().x)
                                            .min(available.y / texture.size_vec2().y)
                                            .max(0.01),
                                ),
                            );
                        },
                    );
                } else {
                    ui.centered_and_justified(|ui| {
                        ui.label("Aguardando foto da pesagem");
                    });
                }
            });
    }
}
fn open_photo(path: &std::path::Path) -> anyhow::Result<()> {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStrExt;
        #[link(name = "shell32")]
        unsafe extern "system" {
            fn ShellExecuteW(
                window: *mut std::ffi::c_void,
                operation: *const u16,
                file: *const u16,
                parameters: *const u16,
                directory: *const u16,
                show: i32,
            ) -> isize;
        }
        let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
        // ShellExecute receives the filename as a separate parameter, never shell command text.
        let result = unsafe {
            ShellExecuteW(
                std::ptr::null_mut(),
                std::ptr::null(),
                wide.as_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                1,
            )
        };
        anyhow::ensure!(result > 32, "Visualizador indisponível");
    }
    #[cfg(not(windows))]
    {
        std::process::Command::new("xdg-open").arg(path).spawn()?;
    }
    Ok(())
}
pub fn format_weight(weight: Option<i64>) -> String {
    let Some(weight) = weight else {
        return "—".into();
    };
    let digits = weight.unsigned_abs().to_string();
    let mut out = String::new();
    if weight < 0 {
        out.push('-');
    }
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push('.');
        }
        out.push(c);
    }
    out
}
#[cfg(test)]
mod tests {
    #[test]
    fn preview_waits_two_seconds_and_resets_when_mouse_leaves() {
        use super::*;
        let mut hover = PreviewHover::default();
        let now = Instant::now();
        assert!(!hover.visible(true, now));
        assert!(!hover.visible(true, now + Duration::from_millis(1999)));
        assert!(hover.visible(true, now + Duration::from_secs(2)));
        assert!(!hover.visible(false, now + Duration::from_secs(3)));
        assert!(!hover.visible(true, now + Duration::from_secs(4)));
        assert!(hover.visible(true, now + Duration::from_secs(6)));
    }
    #[test]
    fn weight_format() {
        assert_eq!(super::format_weight(Some(28500)), "28.500");
        assert_eq!(super::format_weight(Some(-1234)), "-1.234");
        assert_eq!(super::format_weight(None), "—");
    }
}
