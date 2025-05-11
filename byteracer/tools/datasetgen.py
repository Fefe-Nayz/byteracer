#!/usr/bin/env python3
"""
stream_to_labelstudio.py  (v8 – dataset lifecycle & pagination)
────────────────────────────────────────────────────────────────────────
* Live YOLO inference • multi-session recording • frame sampling (--keep)
* HUD:  Saved-count  +  FPS
* Paste LS URLs → /data/… in tasks.json
* Dataset tools:
    - Startup keep/clear prompt if an old dataset exists
    - Manage dataset (paged thumbnails, delete-selected)
    - Prune dataset: delete X % at random
"""

import argparse, itertools, json, os, queue, random, shutil, threading, time, uuid
from math import floor
from pathlib import Path
from tkinter import (
    Tk, Label, Button, Toplevel, Text, messagebox, END, Canvas, Frame,
    Scrollbar, Checkbutton, IntVar, BOTH, NW, VERTICAL, RIGHT, Y, Entry
)

import cv2
from PIL import Image, ImageTk
from ultralytics import YOLO


# ───────────────────────── helpers ───────────────────────── #
def write_classes(names, root: Path):
    (root / "classes.txt").write_text("\n".join(names[i] for i in range(len(names))))


def yolo_to_ls_rect(xc, yc, bw, bh):
    return (xc - bw / 2) * 100, (yc - bh / 2) * 100, bw * 100, bh * 100


def build_ls_json(dataset: Path, names, url_map, json_name="tasks.json"):
    """
    Always add one prediction object.
    If the label file is missing or empty, `result` becomes [] instead of
    omitting the whole prediction array (which confused Label Studio).
    """
    images_dir, labels_dir = dataset / "images", dataset / "labels"
    tasks = []

    for img_path in sorted(images_dir.glob("*.jpg")):
        stemfile = img_path.name
        raw_url  = url_map.get(stemfile)
        image_val = f"/data/{raw_url.lstrip('/')}" if raw_url else f"images/{stemfile}"

        task = {"data": {"image": image_val}, "predictions": []}

        # ---------- build the (single) prediction ----------
        lbl_path = labels_dir / f"{img_path.stem}.txt"
        results = []
        if lbl_path.exists() and lbl_path.stat().st_size:
            h, w = cv2.imread(str(img_path)).shape[:2]
            for line in lbl_path.read_text().splitlines():
                cls, xc, yc, bw, bh, *rest = map(float, line.split())
                x, y, width, height = yolo_to_ls_rect(xc, yc, bw, bh)
                results.append({
                    "id": str(uuid.uuid4()),
                    "type": "rectanglelabels",
                    "from_name": "label",
                    "to_name": "image",
                    "original_width": w,
                    "original_height": h,
                    "image_rotation": 0,
                    "value": {
                        "rotation": 0,
                        "x": x, "y": y,
                        "width": width, "height": height,
                        "rectanglelabels": [names[int(cls)]],
                    },
                    "score": rest[0] if rest else 1.0,
                })

        # Whether `results` is populated or empty, we still push the prediction
        task["predictions"].append({
            "model_version": "auto",
            "result": results          # may be []
        })
        tasks.append(task)

    (dataset / json_name).write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
    return dataset / json_name


# ────────────────── dataset manager (paged) ────────────────── #
class DatasetManager(Toplevel):
    THUMB = 128
    PAGE  = 40             # thumbs per page

    def __init__(self, master, images_dir: Path, labels_dir: Path, update_saved):
        super().__init__(master)
        self.title("Manage dataset")
        self.images_dir, self.labels_dir = images_dir, labels_dir
        self.update_saved = update_saved
        self.all_imgs = sorted(self.images_dir.glob("*.jpg"))
        self.page = 0
        self.selected = set()  # filenames marked across pages
        self.tkimgs = {}       # thumbnail cache {path: PhotoImage}

        # scrollable canvas
        self.canvas = Canvas(self, borderwidth=0)
        vbar = Scrollbar(self, orient=VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side=RIGHT, fill=Y); self.canvas.pack(fill=BOTH, expand=True)
        self.frame = Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.frame, anchor=NW)
        self.frame.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # nav + actions
        nav = Frame(self); nav.pack(fill="x")
        Button(nav, text="<< Prev", command=self.prev_page).pack(side="left")
        Button(nav, text="Next >>", command=self.next_page).pack(side="left")
        self.lbl_page = Label(nav); self.lbl_page.pack(side="left", padx=10)
        Button(nav, text="Delete selected", command=self.delete_selected).pack(side="right")

        self.populate()

    # pagination helpers
    def page_count(self): return max(1, (len(self.all_imgs) + self.PAGE - 1) // self.PAGE)

    def populate(self):
        for w in self.frame.winfo_children(): w.destroy()
        start = self.page * self.PAGE
        imgs = self.all_imgs[start:start + self.PAGE]
        cols = 5
        for idx, img_path in enumerate(imgs):
            row, col = divmod(idx, cols)
            # Create a frame to hold the checkbox and label
            item_frame = Frame(self.frame)
            item_frame.grid(row=row*2, column=col, padx=4, pady=4)
            
            if img_path not in self.tkimgs:  # cache thumb
                pil = Image.open(img_path).resize((self.THUMB, self.THUMB))
                self.tkimgs[img_path] = ImageTk.PhotoImage(pil)
            
            var = IntVar(value=1 if img_path.name in self.selected else 0)
            def _toggle(p=img_path, v=var):
                if v.get(): self.selected.add(p.name)
                else:       self.selected.discard(p.name)
            
            # Add the checkbox with image
            chk = Checkbutton(item_frame, image=self.tkimgs[img_path], variable=var,
                              command=_toggle)
            chk.pack()
            
            # Add the filename label below the image
            filename_label = Label(item_frame, text=img_path.stem, font=("Arial", 8))
            filename_label.pack()
            
        self.lbl_page.config(text=f"Page {self.page+1}/{self.page_count()}  ({len(self.all_imgs)} images)")

    def prev_page(self):
        if self.page > 0:
            self.page -= 1; self.populate()

    def next_page(self):
        if (self.page+1) < self.page_count():
            self.page += 1; self.populate()

    def delete_selected(self):
        if not self.selected:
            messagebox.showinfo("None selected", "Tick some images first."); return
        if not messagebox.askyesno("Confirm", f"Delete {len(self.selected)} image(s)?"):
            return
        deleted = 0
        for fname in list(self.selected):
            img_path = self.images_dir / fname
            lbl_path = self.labels_dir / fname.replace(".jpg", ".txt")
            try:
                img_path.unlink(); deleted += 1
                if lbl_path.exists(): lbl_path.unlink()
                self.all_imgs.remove(img_path)
                self.selected.discard(fname)
            except Exception as e:
                print("Delete error:", e)
        self.update_saved(-deleted)
        self.populate()


# ───────────────────────── main GUI ───────────────────────── #
class StreamGUI:
    def __init__(self, model_path, stream_url, out_dir, conf, keep_pct):
        # paths -----------------------------------------------------------------
        self.out = Path(out_dir)
        self.images_dir = self.out / "images"
        self.labels_dir = self.out / "labels"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.labels_dir.mkdir(exist_ok=True)
        
        # Store stream URL for reconnection if needed
        self.stream_url = stream_url

        # check existing dataset ------------------------------------------------
        existing = list(self.images_dir.glob("*.jpg"))
        if existing:
            keep = messagebox.askyesno(
                "Existing dataset",
                f"Found dataset with {len(existing)} images.\nKeep it?"
            )
            if not keep:
                shutil.rmtree(self.images_dir)
                shutil.rmtree(self.labels_dir, ignore_errors=True)
                self.images_dir.mkdir(); self.labels_dir.mkdir()
                existing.clear()
            else:
                self._ensure_sequential(existing)

        # model -----------------------------------------------------------------
        self.model = YOLO(model_path)
        write_classes(self.model.names, self.out)        # video stream ----------------------------------------------------------
        self.cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        
        # Set specific parameters to handle MJPEG streams correctly
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        
        # If the stream still doesn't open, try alternative approach with explicit MJPEG format
        if not self.cap.isOpened():
            # Release the previous capture attempt
            self.cap.release()
            # Try reopening with more specific options
            self.cap = cv2.VideoCapture()
            self.cap.open(stream_url, cv2.CAP_FFMPEG)
            self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
            
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open stream {stream_url}")

        # parameters ------------------------------------------------------------
        self.conf = conf
        self.keep_mod = int(round(100 / keep_pct)) if keep_pct < 100 else 1

        # stats/state -----------------------------------------------------------
        self.saved = len(existing)
        self.prev_time = time.time()
        self.recording = False
        self.running   = True
        self.frame_id  = itertools.count(start=self.saved)

        # UI --------------------------------------------------------------------
        self.root = Tk(); self.root.title("YOLO live")
        self.lbl  = Label(self.root); self.lbl.pack()

        self.btn_rec = Button(self.root, text="Start recording", command=self.toggle_rec)
        self.btn_rec.pack(fill="x")
        self.btn_urls = Button(self.root, text="Paste LS URLs", 
                               state="normal" if self.saved > 0 else "disabled",
                               command=self.open_url_dialog)
        self.btn_urls.pack(fill="x")
        self.btn_mgr = Button(self.root, text="Manage dataset",
                              command=self.open_manager, state="normal")
        self.btn_mgr.pack(fill="x")
        self.btn_prune = Button(self.root, text="Prune dataset (%)",
                                command=self.prune_dataset)
        self.btn_prune.pack(fill="x")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        # worker thread ---------------------------------------------------------
        self.q = queue.Queue(maxsize=2)
        threading.Thread(target=self.reader_loop, daemon=True).start()
        self.root.after(0, self.display_loop)
        self.root.mainloop()

    def _ensure_sequential(self, current_imgs):
        correct = True
        for expect_idx, img_path in enumerate(current_imgs):
            want = f"frame_{expect_idx:06d}.jpg"
            if img_path.name != want:
                correct = False; break
        if correct:
            return  # nothing to do

        if not messagebox.askyesno(
            "Renumber needed",
            "Dataset filenames are not sequential (gaps detected).\n"
            "Renumber remaining files now?"):
            return

        # Do the renumbering
        for new_idx, img_path in enumerate(sorted(self.images_dir.glob("*.jpg"))):
            new_img = self.images_dir / f"frame_{new_idx:06d}.jpg"
            if img_path != new_img:
                lbl_old = self.labels_dir / img_path.name.replace(".jpg", ".txt")
                lbl_new = self.labels_dir / new_img.name.replace(".jpg", ".txt")
                try:
                    img_path.rename(new_img)
                    if lbl_old.exists():
                        lbl_old.rename(lbl_new)
                except Exception as e:
                    print("Startup rename error:", e)
        messagebox.showinfo("Renumbered", "Dataset filenames fixed.")    # ─── background read / infer ─── #
    def reader_loop(self):
        skip = 0
        consecutive_errors = 0
        max_errors = 5  # Maximum consecutive errors before attempting stream reconnection
        
        while self.running:
            # Check if camera connection is still open
            if not self.cap.isOpened():
                print("Stream connection lost, attempting to reconnect...")
                time.sleep(1)
                self.cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
                continue
                
            try:
                # Attempt to read frame from camera
                ok, frame = self.cap.read()
                
                # Handle failed frame read
                if not ok:
                    consecutive_errors += 1
                    if consecutive_errors >= max_errors:
                        print(f"Multiple frame read errors ({consecutive_errors}), reconnecting...")
                        self.cap.release()
                        time.sleep(0.5)
                        self.cap = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
                        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
                        consecutive_errors = 0
                    time.sleep(0.1)
                    continue
                
                # Frame read succeeded, reset error counter
                consecutive_errors = 0
                
                # Process frame with YOLO model
                res = self.model.predict(frame, conf=self.conf, verbose=False)
                annotated = res[0].plot()

                # Calculate and display FPS
                fps = 1.0 / max(1e-6, time.time() - self.prev_time)
                self.prev_time = time.time()
                
                # Add HUD elements
                h, w = annotated.shape[:2]
                cv2.putText(annotated, f"Saved: {self.saved}", (10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
                text_fps = f"{fps:.1f} FPS"
                (tw, _), _ = cv2.getTextSize(text_fps, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
                cv2.putText(annotated, text_fps, (w - tw - 10, 25),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

                # Send frame to display queue
                try:
                    self.q.put_nowait(annotated)
                except queue.Full:
                    _ = self.q.get_nowait()
                    self.q.put_nowait(annotated)

                # Save selected frames if recording
                if self.recording and skip % self.keep_mod == 0:
                    idx = next(self.frame_id)
                    stem = f"frame_{idx:06d}"
                    cv2.imwrite(str(self.images_dir / f"{stem}.jpg"), frame)
                    with open(self.labels_dir / f"{stem}.txt", "w") as f:
                        for b, c, conf in zip(res[0].boxes.xywhn.cpu(),
                                              res[0].boxes.cls.cpu(),
                                              res[0].boxes.conf.cpu()):
                            xc, yc, bw, bh = b
                            f.write(f"{int(c)} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f} {conf:.6f}\n")
                    self.saved += 1
                skip += 1
                
            except Exception as e:
                print(f"Error in reader loop: {e}")
                time.sleep(0.1)
                consecutive_errors += 1
            if self.recording and skip % self.keep_mod == 0:
                idx = next(self.frame_id)
                stem = f"frame_{idx:06d}"
                cv2.imwrite(str(self.images_dir / f"{stem}.jpg"), frame)
                with open(self.labels_dir / f"{stem}.txt", "w") as f:
                    for b, c, conf in zip(res[0].boxes.xywhn.cpu(),
                                          res[0].boxes.cls.cpu(),
                                          res[0].boxes.conf.cpu()):
                        xc, yc, bw, bh = b
                        f.write(f"{int(c)} {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f} {conf:.6f}\n")
                self.saved += 1
            skip += 1

    # ─── GUI update loop ─── #
    def display_loop(self):
        if not self.running: return
        try:
            frame = self.q.get_nowait()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.lbl.img = img; self.lbl.configure(image=img)
        except queue.Empty:
            pass
        self.root.after(33, self.display_loop)

    # ─── callbacks ─── #
    def toggle_rec(self):
        self.recording = not self.recording
        self.btn_rec.configure(text="Stop recording" if self.recording else "Start recording")
        # Only enable Paste LS URLs button if we have saved images
        if not self.recording and self.saved > 0:
            self.btn_urls.configure(state="normal")
        elif self.recording:
            self.btn_urls.configure(state="disabled")

    def open_url_dialog(self):
        dlg = Toplevel(self.root); dlg.title("Paste Label-Studio URLs")
        txt = Text(dlg, width=90, height=25); txt.pack()
        Button(dlg, text="Generate JSON",
               command=lambda: self.generate_json(txt.get("1.0", END), dlg)
               ).pack(fill="x")

    def generate_json(self, raw, dlg):
        url_map = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line: continue
            base = os.path.basename(line)
            base = base[base.index("frame_"):] if "frame_" in base else base
            url_map[base] = line
        if not url_map:
            messagebox.showwarning("No URLs", "Paste some paths first."); return
        out_json = build_ls_json(self.out, self.model.names, url_map)
        messagebox.showinfo("Done", f"tasks.json written:\n{out_json}")
        dlg.destroy(); self.close()

    def open_manager(self):
        DatasetManager(self.root, self.images_dir, self.labels_dir, self._inc_saved)

    def prune_dataset(self):
        dlg = Toplevel(self.root); dlg.title("Prune dataset")
        
        # Create frame for percentage input
        frame1 = Frame(dlg); frame1.pack(fill="x", pady=5)
        Label(frame1, text="Delete % of images:").pack(side="left")
        pct_entry = Entry(frame1, width=10); pct_entry.insert(0, "10"); pct_entry.pack(side="left", padx=5)
        
        # Create frame for start index input
        frame2 = Frame(dlg); frame2.pack(fill="x", pady=5)
        Label(frame2, text="Start pruning from image #:").pack(side="left")
        start_entry = Entry(frame2, width=10); start_entry.insert(0, "0"); start_entry.pack(side="left", padx=5)
        
        # Create a checkbox for renumbering option
        renumber_var = IntVar(value=1)
        frame3 = Frame(dlg); frame3.pack(fill="x", pady=5)
        Checkbutton(frame3, text="Renumber remaining files after deletion", variable=renumber_var).pack(anchor="w")
        
        def _run():
            try:
                pct = float(pct_entry.get())
                start_idx = int(start_entry.get())
                if not (0 < pct < 100): raise ValueError("Invalid percentage")
                if start_idx < 0: raise ValueError("Invalid start index")
            except ValueError as e:
                messagebox.showerror("Invalid Input", "Enter a percentage between 0-100 and a non-negative start index"); return
                
            # Get all image files and sort them
            all_images = sorted(list(self.images_dir.glob("*.jpg")))
            total = len(all_images)
            
            if start_idx >= total:
                messagebox.showinfo("Invalid Index", f"Start index {start_idx} exceeds total images ({total})"); return
                
            # Only consider images from the start index
            eligible_images = all_images[start_idx:]
            eligible_count = len(eligible_images)
            
            # Calculate how many to delete from eligible images
            n_del = floor(eligible_count * pct / 100)
            if not n_del:
                messagebox.showinfo("None", "Percentage too small or not enough eligible images."); return
                
            if not messagebox.askyesno("Confirm", f"Delete {n_del} images from image #{start_idx} onward?\n(Total: {total} images, Eligible: {eligible_count} images)"):
                return
                  # Randomly sample from eligible images
            files = random.sample(eligible_images, n_del)
            deleted = 0
            for img in files:
                lbl = self.labels_dir / img.name.replace(".jpg", ".txt")
                try:
                    img.unlink(); deleted += 1
                    if lbl.exists(): lbl.unlink()
                except Exception as e:
                    print("Del error:", e)
            
            # Renumber remaining images to ensure sequential naming
            if deleted > 0 and messagebox.askyesno("Renumber Files", 
                                              "Would you like to renumber remaining files to ensure sequential naming?"):
                # Get remaining images and sort them
                remaining_images = sorted(list(self.images_dir.glob("*.jpg")))
                renamed = 0
                
                # Notify user with progress dialog
                progress_dlg = Toplevel(dlg)
                progress_dlg.title("Renumbering Files")
                progress_lbl = Label(progress_dlg, text="Renumbering files...")
                progress_lbl.pack(pady=10, padx=20)
                
                # Create new sequential filenames
                for idx, img_path in enumerate(remaining_images):
                    new_name = f"frame_{idx:06d}.jpg"
                    lbl_path = self.labels_dir / img_path.name.replace(".jpg", ".txt")
                    new_lbl_name = f"frame_{idx:06d}.txt"
                    
                    # Skip if already has the correct name
                    if img_path.name == new_name:
                        continue
                        
                    try:
                        # Rename both image and label if exists
                        img_path.rename(self.images_dir / new_name)
                        renamed += 1
                        if lbl_path.exists():
                            lbl_path.rename(self.labels_dir / new_lbl_name)
                        
                        # Update progress occasionally
                        if idx % 10 == 0:
                            progress_lbl.config(text=f"Renumbering files... {idx}/{len(remaining_images)}")
                            progress_dlg.update()
                    except Exception as e:
                        print(f"Rename error for {img_path.name}: {e}")
                  # Update frame_id counter to start from the new count
                self.root.after_idle(lambda: setattr(self.root.master, 'frame_id', itertools.count(start=len(remaining_images))))
                progress_dlg.destroy()
                messagebox.showinfo("Renumbering Complete", 
                                    f"Deleted {deleted} images and renumbered {renamed} remaining files.")
            else:
                messagebox.showinfo("Done", f"Deleted {deleted} images.")
                
            self._inc_saved(-deleted)
            dlg.destroy()
            
        Button(dlg, text="Delete", command=_run).pack(fill="x", pady=10)

    def _inc_saved(self, delta):
        self.saved = max(0, self.saved + delta)
        # Update URL button state based on whether we have images
        if not self.recording:
            self.btn_urls.configure(state="normal" if self.saved > 0 else "disabled")

    def close(self):
        self.running = False
        self.cap.release()
        self.root.destroy()


# ───────────────────────── CLI ───────────────────────── #
def parse_args():
    p = argparse.ArgumentParser(description="YOLO ↔ Label-Studio recorder with dataset manager")
    p.add_argument("--model", required=True)
    p.add_argument("--url", default="http://192.168.1.50:9000/mjpg", 
                  help="MJPEG stream URL. If you experience 'Expected boundary' errors, ensure the URL ends with .mjpg or /mjpg")
    p.add_argument("--output", default="dataset")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--keep", type=float, default=100, help="Percent of frames to save")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if not (0 < args.keep <= 100):
        raise SystemExit("--keep must be in (0,100]")
    StreamGUI(args.model, args.url, args.output, args.conf, args.keep)
