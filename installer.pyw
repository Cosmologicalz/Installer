import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, Toplevel
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import sys
import subprocess # For opening files in default editor

# Ensure Pillow is available for dummy icon generation
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow not found. Install it with 'pip install Pillow' to generate a dummy icon if 'icon.png' is missing.")
    print("The app will run, but may not display an icon without 'Pillow' or 'icon.png'.")


class GitHubInstallerApp(tk.Tk):
    """
    A simple Python-based .pyw installer for GitHub repositories.
    This application allows users to input a GitHub repository URL,
    select a download directory, and provides basic logging.
    Future versions will include full download, extraction, and
    installation features.
    """

    def __init__(self):
        super().__init__()

        self.resources_path = self._get_resource_path("resources")
        self.log_file = os.path.join(self.resources_path, "log.log")
        self.his_log_file = os.path.join(self.resources_path, "his.log")
        self.dow_log_file = os.path.join(self.resources_path, "dow.log")
        self.crash_log_file = os.path.join(self.resources_path, "crash.log")
        self.data_json_file = os.path.join(self.resources_path, "data.json")

        self.logger = self._setup_logging()
        self._startup_checks()

        self.app_version = self._load_version() # Load version before UI setup
        self.title(f"GitHub Repo Installer - {self.app_version}")
        self.geometry("800x600")

        # Handle icon.png (create dummy if not exists, then load)
        icon_path = self._get_resource_path("icon.png")
        if not os.path.exists(icon_path):
            self._create_dummy_icon(icon_path)
        try:
            self.iconphoto(False, tk.PhotoImage(file=icon_path))
        except tk.TclError:
            self.logger.warning(f"Could not load icon from {icon_path}. Ensure it's a valid PNG.")


        self._setup_ui()
        self._load_app_state() # Load other app state after UI is ready

        self.logger.info(f"Application started successfully. Version: {self.app_version}")
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Developer console window reference
        self.developer_console_window = None

    def _get_resource_path(self, relative_path):
        """
        Get the absolute path to a resource, handling both development
        and PyInstaller bundled environments.
        """
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except AttributeError:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def _create_dummy_icon(self, path):
        """Creates a dummy icon.png if it doesn't exist, using Pillow."""
        try:
            img = Image.new('RGB', (32, 32), color=(73, 109, 137))
            d = ImageDraw.Draw(img)
            d.text((8, 5), "G", fill=(255, 255, 255), font_size=20) # Use font_size for better scaling
            img.save(path)
            self.logger.info(f"Created dummy icon.png at {path}")
        except Exception as e:
            self.logger.warning(f"Failed to create dummy icon.png: {e}. Please ensure Pillow is installed.")

    def _setup_logging(self):
        """
        Sets up the custom logging system for the application,
        directing output to console, main log file, and GUI.
        """
        logger = logging.getLogger("GitHubInstaller")
        logger.setLevel(logging.DEBUG)

        # Clear existing handlers to prevent duplicates on potential re-init
        for handler in list(logger.handlers):
            logger.removeHandler(handler)

        # Custom formatter for file and console
        formatter = logging.Formatter(
            fmt="[%(asctime)s][%(levelname)s] --- %(message)s --- [%(filename)s - %(funcName)s - %(lineno)d]",
            datefmt="%H:%M:%S"
        )
        # Formatter for GUI (simpler, without full context)
        gui_formatter = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s", datefmt="%H:%M:%S")

        # File handler for log.log (general log)
        file_handler = RotatingFileHandler(self.log_file, maxBytes=10*1024*1024, backupCount=5)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console handler (for debugging if run as .py)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Custom handler for main GUI text widget
        self.main_gui_log_handler = GUILogHandler(self, lambda msg: self.after(0, self._append_to_log_display, msg))
        self.main_gui_log_handler.setFormatter(gui_formatter)
        logger.addHandler(self.main_gui_log_handler)

        return logger

    def _log_to_specific_file(self, level, message, filename, exc_info=None):
        """
        Logs a message to a specific log file in addition to the main log.
        This uses a separate logger to avoid issues with main logger's handlers.
        """
        specific_logger = logging.getLogger(f"SpecificLogger_{os.path.basename(filename)}")
        specific_logger.setLevel(logging.DEBUG)
        if not specific_logger.handlers: # Only add handler once
            file_handler = RotatingFileHandler(filename, maxBytes=10*1024*1024, backupCount=5)
            formatter = logging.Formatter(
                fmt="[%(asctime)s][%(levelname)s] --- %(message)s --- [%(filename)s - %(funcName)s - %(lineno)d]",
                datefmt="%H:%M:%S"
            )
            file_handler.setFormatter(formatter)
            specific_logger.addHandler(file_handler)

        if level == logging.INFO:
            specific_logger.info(message)
        elif level == logging.WARNING:
            specific_logger.warning(message)
        elif level == logging.ERROR:
            specific_logger.error(message, exc_info=exc_info)
        elif level == logging.CRITICAL:
            specific_logger.critical(message, exc_info=exc_info)

    def _startup_checks(self):
        """
        Performs essential startup checks:
        - Creates 'resources' folder if missing.
        - Ensures all required log files and data.json exist, recreating them if missing.
        """
        self.logger.info("Performing startup checks...")
        try:
            if not os.path.exists(self.resources_path):
                os.makedirs(self.resources_path)
                self.logger.info(f"Created resources folder: {self.resources_path}")

            # Ensure data.json exists first to load version
            if not os.path.exists(self.data_json_file):
                with open(self.data_json_file, "w") as f:
                    json.dump({"github_history": [], "download_dir": os.getcwd(), "current_version": "v0.1-pre-alpha"}, f, indent=4)
                self.logger.info(f"Created missing data.json file: {os.path.basename(self.data_json_file)}")

            # Now, check and create log files
            required_files = {
                self.log_file: "[TIMESTAMP] --- Application Session Start ---",
                self.his_log_file: "[TIMESTAMP] --- History Log Start ---",
                self.dow_log_file: "[TIMESTAMP] --- Download Log Start ---",
                self.crash_log_file: "[TIMESTAMP] --- Crash Log Start ---"
            }

            for file_path, header_content in required_files.items():
                if not os.path.exists(file_path):
                    with open(file_path, "a") as f:
                        f.write(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {header_content}\n")
                    self.logger.info(f"Created missing log file: {os.path.basename(file_path)}")

            self.logger.info("Startup checks complete. All resources are ready.")

            # Append session start header to log.log
            with open(self.log_file, "a") as f:
                f.write(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} --- Application Session Start ---\n")

        except Exception as e:
            self.logger.critical(f"Fatal error during startup checks: {e}", exc_info=True)
            self._log_to_specific_file(logging.CRITICAL, f"Fatal error during startup checks: {e}", self.crash_log_file, exc_info=True)
            messagebox.showerror("Critical Error", f"The application encountered a fatal error during startup and cannot proceed:\n{e}\nCheck crash.log for details.")
            self.destroy() # Close the application if critical files can't be set up

    def _load_version(self):
        """Loads the current version from data.json."""
        try:
            with open(self.data_json_file, "r") as f:
                data = json.load(f)
                version = data.get("current_version", "vUnknown")
                self.logger.info(f"Loaded application version: {version}")
                return version
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.warning("data.json not found or corrupted during version load. Defaulting to v0.1-pre-alpha.")
            return "v0.1-pre-alpha"

    def _save_version(self):
        """Saves the current version to data.json."""
        try:
            with open(self.data_json_file, "r+") as f:
                data = json.load(f)
                data["current_version"] = self.app_version
                f.seek(0) # Rewind to beginning
                json.dump(data, f, indent=4)
                f.truncate() # Trim any remaining old content
            self.logger.debug(f"Saved application version: {self.app_version}")
        except Exception as e:
            self.logger.error(f"Error saving application version to data.json: {e}", exc_info=True)


    def _setup_ui(self):
        """
        Sets up the main graphical user interface elements.
        """
        # Configure grid for responsiveness
        self.grid_rowconfigure(0, weight=0) # Menu bar row
        self.grid_rowconfigure(1, weight=0) # GitHub input row
        self.grid_rowconfigure(2, weight=0) # Quick options row
        self.grid_rowconfigure(3, weight=1) # Log display row
        self.grid_columnconfigure(0, weight=1) # Main column

        # --- Menu Bar ---
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File Menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Exit", command=self._on_closing)

        # Options Menu
        options_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Options", menu=options_menu)

        # ZIP Options Submenu
        zip_options_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="ZIP Options", menu=zip_options_menu)
        self.extract_on_download_var = tk.BooleanVar(value=True)
        zip_options_menu.add_checkbutton(label="Extract on download", variable=self.extract_on_download_var)
        self.create_folder_on_extract_var = tk.BooleanVar(value=True)
        zip_options_menu.add_checkbutton(label="Create folder for ZIP", variable=self.create_folder_on_extract_var)
        self.delete_zip_after_extract_var = tk.BooleanVar(value=False)
        zip_options_menu.add_checkbutton(label="Delete ZIP after extraction", variable=self.delete_zip_after_extract_var)

        # Installer Options Submenu
        installer_options_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Installer Options", menu=installer_options_menu)
        installer_options_menu.add_command(label="Move resources folder", command=self._move_resources_folder)
        installer_options_menu.add_command(label="Update Installer", command=self._update_installer)

        # Handle Files Menu
        handle_files_menu = tk.Menu(options_menu, tearoff=0)
        options_menu.add_cascade(label="Handle Files", menu=handle_files_menu)
        handle_files_menu.add_command(label="GitHub Links (data.json)", command=lambda: self._open_content_viewer_window(self.data_json_file, "data.json Content", clearable=False))
        handle_files_menu.add_command(label="General Logs (log.log)", command=lambda: self._open_content_viewer_window(self.log_file, "General Logs (log.log)", clearable=True))
        handle_files_menu.add_command(label="Download History (dow.log)", command=lambda: self._open_content_viewer_window(self.dow_log_file, "Download History (dow.log)", clearable=True))
        handle_files_menu.add_command(label="Crash History (his.log)", command=lambda: self._open_content_viewer_window(self.his_log_file, "Crash History (his.log)", clearable=True))
        handle_files_menu.add_command(label="Fatal Crash Logs (crash.log)", command=lambda: self._open_content_viewer_window(self.crash_log_file, "Fatal Crash Logs (crash.log)", clearable=True))


        # Developer Tools Menu
        dev_tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Developer Tools", menu=dev_tools_menu)
        dev_tools_menu.add_command(label="Open Developer Console", command=self._open_developer_console)
        dev_tools_menu.add_command(label="Clear Live Log", command=self._clear_live_log)

        # --- GitHub Input Frame ---
        gh_frame = ttk.LabelFrame(self, text="GitHub Repository", padding="10")
        gh_frame.grid(row=1, column=0, padx=10, pady=5, sticky="ew")
        gh_frame.grid_columnconfigure(0, weight=1) # Entry takes most space

        ttk.Label(gh_frame, text="Repository URL:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        
        self.github_url_var = tk.StringVar()
        self.github_url_combobox = ttk.Combobox(
            gh_frame,
            textvariable=self.github_url_var,
            width=50 # Adjust width as needed
        )
        self.github_url_combobox.grid(row=0, column=1, padx=5, pady=2, sticky="ew")
        self.github_url_combobox.bind("<<ComboboxSelected>>", self._on_github_url_selected) # Event for selection

        download_button = ttk.Button(gh_frame, text="Download/Install", command=self._start_download_process)
        download_button.grid(row=0, column=2, padx=5, pady=2)

        # --- Quick Options Frame ---
        options_frame = ttk.LabelFrame(self, text="Quick Options", padding="10")
        options_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        options_frame.grid_columnconfigure(0, weight=0)
        options_frame.grid_columnconfigure(1, weight=1) # Directory entry takes most space

        ttk.Label(options_frame, text="Download Directory:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.download_dir_var = tk.StringVar(value=os.getcwd()) # Default to current working directory
        self.download_dir_entry = ttk.Entry(options_frame, textvariable=self.download_dir_var, state="readonly")
        self.download_dir_entry.grid(row=0, column=1, padx=5, pady=2, sticky="ew")

        browse_button = ttk.Button(options_frame, text="Browse", command=self._browse_download_directory)
        browse_button.grid(row=0, column=2, padx=5, pady=2)

        # --- Live Log Display ---
        self.log_display_frame = ttk.LabelFrame(self, text="Live Log", padding="10")
        self.log_display_frame.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        self.log_display_frame.grid_rowconfigure(0, weight=1)
        self.log_display_frame.grid_columnconfigure(0, weight=1)

        self.log_text_widget = scrolledtext.ScrolledText(
            self.log_display_frame,
            wrap=tk.WORD,
            state="disabled", # Start as disabled
            height=15, # Initial height
            font=("Consolas", 10)
        )
        self.log_text_widget.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    def _append_to_log_display(self, message):
        """Appends a message to the main window's live log ScrolledText widget."""
        self.log_text_widget.configure(state="normal")
        self.log_text_widget.insert(tk.END, message + "\n")
        self.log_text_widget.see(tk.END) # Auto-scroll to bottom
        self.log_text_widget.configure(state="disabled")

    def _clear_live_log(self):
        """Clears the content of the main window's live log display."""
        self.log_text_widget.configure(state="normal")
        self.log_text_widget.delete(1.0, tk.END)
        self.log_text_widget.configure(state="disabled")
        self.logger.info("Main live log display cleared.")

    def _browse_download_directory(self):
        """Opens a directory chooser dialog and updates the download directory."""
        self.logger.debug("Opening directory browser...")
        new_dir = filedialog.askdirectory(initialdir=self.download_dir_var.get())
        if new_dir:
            self.download_dir_var.set(new_dir)
            self.logger.info(f"Download directory set to: {new_dir}")
            self._save_app_state() # Save changes immediately

    def _load_app_state(self):
        """Loads saved GitHub links and app state from data.json."""
        self.logger.info("Loading application state from data.json...")
        try:
            with open(self.data_json_file, "r") as f:
                data = json.load(f)
                
                # Load GitHub history
                history = data.get("github_history", [])
                self.github_url_combobox["values"] = history
                if history:
                    self.github_url_var.set(history[0]) # Set first item as default if history exists

                # Load download directory
                saved_dir = data.get("download_dir")
                if saved_dir and os.path.isdir(saved_dir):
                    self.download_dir_var.set(saved_dir)
                else:
                    self.download_dir_var.set(os.getcwd()) # Fallback to current working directory
                    self.logger.warning(f"Saved download directory '{saved_dir}' not found or invalid. Resetting to current working directory.")

                # Load quick options
                self.extract_on_download_var.set(data.get("extract_on_download", True))
                self.create_folder_on_extract_var.set(data.get("create_folder_on_extract", True))
                self.delete_zip_after_extract_var.set(data.get("delete_zip_after_extract", False))

                # Note: App version is loaded separately by _load_version()

                self.logger.info("Application state loaded.")
        except FileNotFoundError:
            self.logger.warning("data.json not found during app state load. Initializing with default state.")
            self._save_app_state() # Create a new one
        except json.JSONDecodeError:
            self.logger.error("Error decoding data.json during app state load. File might be corrupted. Initializing with default state.", exc_info=True)
            self._log_to_specific_file(logging.ERROR, "Error decoding data.json. File might be corrupted.", self.crash_log_file, exc_info=True)
            self._save_app_state() # Overwrite corrupted file
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while loading app state: {e}", exc_info=True)
            self._log_to_specific_file(logging.ERROR, f"An unexpected error occurred while loading app state: {e}", self.crash_log_file, exc_info=True)


    def _save_app_state(self):
        """Saves current GitHub links and app state to data.json."""
        self.logger.info("Saving application state to data.json...")
        try:
            # Get current history and ensure uniqueness and order
            current_url = self.github_url_var.get()
            history = list(self.github_url_combobox["values"])
            if current_url and current_url not in history:
                history.insert(0, current_url) # Add new URL to the top
            elif current_url in history:
                history.remove(current_url)
                history.insert(0, current_url) # Move existing URL to the top
            
            # Limit history to, say, 10 items
            history = history[:10]
            self.github_url_combobox["values"] = history # Update combobox values

            app_state = {
                "github_history": history,
                "download_dir": self.download_dir_var.get(),
                "extract_on_download": self.extract_on_download_var.get(),
                "create_folder_on_extract": self.create_folder_on_extract_var.get(),
                "delete_zip_after_extract": self.delete_zip_after_extract_var.get(),
                "current_version": self.app_version # Save the current version
            }
            with open(self.data_json_file, "w") as f:
                json.dump(app_state, f, indent=4)
            self.logger.info("Application state saved.")
        except Exception as e:
            self.logger.error(f"Error saving application state: {e}", exc_info=True)
            self._log_to_specific_file(logging.ERROR, f"Error saving application state: {e}", self.crash_log_file, exc_info=True)

    def _on_github_url_selected(self, event):
        """Handles when a URL is selected from the combobox dropdown."""
        selected_url = self.github_url_combobox.get()
        self.github_url_var.set(selected_url)
        self.logger.debug(f"GitHub URL selected from history: {selected_url}")

    def _start_download_process(self):
        """Initiates the GitHub content download and installation process."""
        repo_url = self.github_url_var.get()
        download_dir = self.download_dir_var.get()
        self._save_app_state() # Save the current URL to history

        if not repo_url:
            messagebox.showwarning("Input Error", "Please enter a GitHub repository URL.")
            self.logger.warning("Download attempt failed: No GitHub URL provided.")
            return
        
        if not os.path.isdir(download_dir):
            messagebox.showerror("Invalid Directory", f"The specified download directory does not exist:\n{download_dir}")
            self.logger.error(f"Download attempt failed: Invalid download directory '{download_dir}'.")
            return

        self.logger.info(f"Attempting to download from GitHub: {repo_url}")
        self.logger.info(f"Target download directory: {download_dir}")
        self._log_to_specific_file(logging.INFO, f"Download initiated: {repo_url} to {download_dir}", self.dow_log_file)

        # Placeholder for actual download and installation logic
        messagebox.showinfo("Download Initiated",
                            f"Download process for '{repo_url}' initiated to '{download_dir}'.\n"
                            "This feature is under development. See live log for progress.")
        self.logger.info("Download/Installation feature is a placeholder. No actual download occurred.")
        self.logger.debug(f"Quick Options: Extract={self.extract_on_download_var.get()}, CreateFolder={self.create_folder_on_extract_var.get()}, DeleteZIP={self.delete_zip_after_extract_var.get()}")


    # --- Menu Bar Action Stubs ---
    def _move_resources_folder(self):
        """Stub for moving the resources folder."""
        self.logger.info("Attempted to move resources folder. (Feature not yet implemented)")
        messagebox.showinfo("Feature Not Implemented", "Moving the resources folder is not yet implemented.")

    def _update_installer(self):
        """Stub for updating the installer."""
        self.logger.info("Attempted to update installer. (Feature not yet implemented)")
        messagebox.showinfo("Feature Not Implemented", "Updating the installer is not yet implemented.")

    def _open_content_viewer_window(self, file_path, title, clearable=False):
        """Opens a new Toplevel window to display file content, with an optional clear button."""
        viewer_window = Toplevel(self)
        viewer_window.title(title)
        viewer_window.geometry("700x500")
        viewer_window.transient(self) # Make it appear on top of the main window
        viewer_window.grab_set() # Make it modal (user must interact with it)
        viewer_window.protocol("WM_DELETE_WINDOW", viewer_window.destroy)

        # Configure grid for responsiveness
        viewer_window.grid_rowconfigure(0, weight=1)
        viewer_window.grid_columnconfigure(0, weight=1)

        text_widget = scrolledtext.ScrolledText(
            viewer_window,
            wrap=tk.WORD,
            state="disabled",
            font=("Consolas", 10),
            padx=10, pady=10
        )
        text_widget.grid(row=0, column=0, sticky="nsew")

        try:
            with open(file_path, "r") as f:
                content = f.read()
            text_widget.configure(state="normal")
            text_widget.insert(tk.END, content)
            text_widget.see(tk.END)
            text_widget.configure(state="disabled")
            self.logger.info(f"Opened file '{os.path.basename(file_path)}' in new viewer window.")
        except FileNotFoundError:
            messagebox.showerror("Error", f"File not found: {file_path}")
            text_widget.configure(state="normal")
            text_widget.insert(tk.END, f"Error: File not found at {file_path}")
            text_widget.configure(state="disabled")
            self.logger.error(f"File not found for viewer: {file_path}", exc_info=True)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read file: {file_path}\n{e}")
            text_widget.configure(state="normal")
            text_widget.insert(tk.END, f"Error reading file: {e}")
            text_widget.configure(state="disabled")
            self.logger.error(f"Error reading file for viewer {file_path}: {e}", exc_info=True)

        if clearable:
            clear_button_frame = ttk.Frame(viewer_window)
            clear_button_frame.grid(row=1, column=0, pady=5)
            clear_button = ttk.Button(clear_button_frame, text="Clear Log", command=lambda: self._clear_log_file(file_path, text_widget))
            clear_button.pack()

        viewer_window.wait_window(viewer_window) # Wait for this window to close

    def _clear_log_file(self, file_path, text_widget):
        """Clears the content of a log file and updates the associated text widget."""
        if messagebox.askyesno("Clear Log", f"Are you sure you want to clear '{os.path.basename(file_path)}'? This action cannot be undone."):
            try:
                with open(file_path, "w") as f:
                    f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} --- Log Cleared ---\n")
                
                text_widget.configure(state="normal")
                text_widget.delete(1.0, tk.END)
                text_widget.insert(tk.END, f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} --- Log Cleared ---\n")
                text_widget.configure(state="disabled")
                self.logger.info(f"Cleared log file: {os.path.basename(file_path)}")
                self._log_to_specific_file(logging.INFO, f"Log file cleared.", file_path) # Log this action to the cleared file itself.
            except Exception as e:
                messagebox.showerror("Error", f"Could not clear log file: {file_path}\n{e}")
                self.logger.error(f"Error clearing log file {file_path}: {e}", exc_info=True)

    def _open_developer_console(self):
        """Opens a new Toplevel window for developer console with live log."""
        if self.developer_console_window and self.developer_console_window.winfo_exists():
            self.developer_console_window.focus_set()
            return

        self.developer_console_window = Toplevel(self)
        self.developer_console_window.title("Developer Console - Live Log")
        self.developer_console_window.geometry("900x600")
        self.developer_console_window.transient(self)
        self.developer_console_window.protocol("WM_DELETE_WINDOW", self._on_developer_console_close)

        self.developer_console_window.grid_rowconfigure(0, weight=1)
        self.developer_console_window.grid_columnconfigure(0, weight=1)

        self.developer_console_text = scrolledtext.ScrolledText(
            self.developer_console_window,
            wrap=tk.WORD,
            state="disabled",
            font=("Consolas", 9),
            padx=5, pady=5
        )
        self.developer_console_text.grid(row=0, column=0, sticky="nsew")

        # Add a new GUI log handler specifically for this console
        self.console_log_handler = GUILogHandler(self, lambda msg: self.after(0, self._append_to_developer_console, msg))
        # Use the same formatter as main GUI log for simplicity in the console
        self.console_log_handler.setFormatter(logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        self.logger.addHandler(self.console_log_handler)
        self.logger.info("Developer Console opened. Live logging redirected.")

        # Optionally, add a simple command input for future interactive features
        # command_frame = ttk.Frame(self.developer_console_window)
        # command_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        # ttk.Label(command_frame, text=">>>").pack(side=tk.LEFT)
        # command_entry = ttk.Entry(command_frame)
        # command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        # command_entry.bind("<Return>", self._execute_console_command) # Future feature

    def _append_to_developer_console(self, message):
        """Appends a message to the developer console's text widget."""
        if self.developer_console_text and self.developer_console_text.winfo_exists():
            self.developer_console_text.configure(state="normal")
            self.developer_console_text.insert(tk.END, message + "\n")
            self.developer_console_text.see(tk.END)
            self.developer_console_text.configure(state="disabled")

    def _on_developer_console_close(self):
        """Removes the console's log handler when the developer console is closed."""
        self.logger.info("Developer Console closed. Removing its log handler.")
        if hasattr(self, 'console_log_handler') and self.console_log_handler in self.logger.handlers:
            self.logger.removeHandler(self.console_log_handler)
        self.developer_console_window.destroy()
        self.developer_console_window = None # Clear reference


    def _on_closing(self):
        """Handles application shutdown, saving state and logging exit."""
        self.logger.info("Application is closing.")
        self._log_to_specific_file(logging.INFO, "Application closed.", self.his_log_file)
        self._save_app_state()
        self.destroy()
        sys.exit(0)


class GUILogHandler(logging.Handler):
    """
    A custom logging handler that sends log records to a Tkinter ScrolledText widget.
    Takes a callback function for thread-safe GUI updates.
    """
    def __init__(self, app_instance, append_callback):
        super().__init__()
        self.app = app_instance
        self.append_callback = append_callback # Callback to update the GUI widget

    def emit(self, record):
        log_entry = self.format(record)
        # Use the provided callback for thread-safe GUI updates
        self.append_callback(log_entry)


if __name__ == "__main__":
    app = GitHubInstallerApp()
    app.mainloop()
