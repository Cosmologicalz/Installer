import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, Toplevel
import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
import sys
import subprocess # For opening files in default editor and running restart script
import shutil # For moving directories
import time # For delays in restart scripts
import tempfile # For temporary files/directories during update
import threading # For running download in background
import zipfile # For extracting zip files

# Try to import requests for GitHub API interaction. If not found, notify user.
try:
    import requests
except ImportError:
    requests = None
    print("Warning: 'requests' library not found. Update/Download features will be unavailable.")

# Ensure Pillow is available for dummy icon generation
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None
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

    DEFAULT_APP_VERSION = "v0.3.1" # Updated default version for extraction feature
    GITHUB_REPO_FOR_UPDATES_API = "https://api.github.com/repos/Cosmologicalz/Installer/releases/latest"
    # Direct raw content link for the .pyw file (assuming main branch always has the latest for this repo)
    GITHUB_RAW_PYW_URL = "https://raw.githubusercontent.com/Cosmologicalz/Installer/refs/heads/main/installer.pyw"
    INSTALLER_FILENAME = os.path.basename(sys.argv[0]) # Name of the current .pyw file

    def __init__(self):
        super().__init__()

        # Determine the application's root directory (where the .pyw file is)
        self.app_root_path = self._get_app_root_path()
        # Path to the specific config file that stores resources folder location
        self.path_config_file = os.path.join(self.app_root_path, "installer_path_config.json")
        
        # Determine the actual path to the 'resources' folder based on config
        self.resources_path = self._determine_resource_folder_path()

        # --- CRITICAL FIX START ---
        # Ensure the resources directory exists BEFORE setting up logging.
        # Logging handlers will try to create/open log files in this directory.
        if not os.path.exists(self.resources_path):
            try:
                os.makedirs(self.resources_path, exist_ok=True)
                # Print directly as logger is not fully set up yet
                print(f"INFO: Created missing resources folder: {self.resources_path}")
            except Exception as e:
                print(f"CRITICAL: Failed to create resources folder {self.resources_path}: {e}")
                messagebox.showerror("Critical Error", f"Failed to create essential 'resources' folder:\n{e}\nApplication cannot proceed.")
                sys.exit(1) # Exit if we can't even create the resources folder
        # --- CRITICAL FIX END ---


        # Define paths for log and data files, now relative to the determined resources_path
        self.log_file = os.path.join(self.resources_path, "log.log")
        self.his_log_file = os.path.join(self.resources_path, "his.log")
        self.dow_log_file = os.path.join(self.resources_path, "dow.log")
        self.crash_log_file = os.path.join(self.resources_path, "crash.log")
        self.data_json_file = os.path.join(self.resources_path, "data.json")
        # Icon path is now inside resources
        self.icon_path = os.path.join(self.resources_path, "icon.png")


        # Set up logging now that resources folder is guaranteed to exist
        self.logger = self._setup_logging() 
        self._startup_checks() # Perform further checks on individual files and version sync

        self.app_version = self._load_version() # Load version from data.json
        self.title(f"GitHub Repo Installer - {self.app_version}")
        self.geometry("800x600")

        # Handle icon.png (create dummy if not exists, then load)
        if not os.path.exists(self.icon_path):
            self._create_dummy_icon(self.icon_path)
        try:
            self.iconphoto(False, tk.PhotoImage(file=self.icon_path))
        except tk.TclError:
            self.logger.warning(f"Could not load icon from {self.icon_path}. Ensure it's a valid PNG.")


        self._setup_ui()
        self._load_app_state() # Load other app state after UI is ready

        self.logger.info(f"Application started successfully. Version: {self.app_version}")
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Developer console window reference
        self.developer_console_window = None

    def _get_app_root_path(self):
        """Gets the root directory where the .pyw executable is located."""
        try:
            # PyInstaller creates a temp folder and stores path in _MEIPASS
            base_path = sys._MEIPASS
        except AttributeError:
            # For development, get the directory of the script itself
            base_path = os.path.abspath(os.path.dirname(sys.argv[0]))
        return base_path

    def _determine_resource_folder_path(self):
        """
        Determines the absolute path to the 'resources' folder.
        It first checks 'installer_path_config.json' for a stored path.
        If not found or invalid, it defaults to a 'resources' folder
        inside the application's root directory.
        """
        app_root = self._get_app_root_path()
        
        # Ensure installer_path_config.json exists and is initialized
        # This check must happen before logging is fully set up, so it's simple file ops.
        if not os.path.exists(self.path_config_file):
            # If config file doesn't exist, create it with default path (app_root)
            try:
                with open(self.path_config_file, "w") as f:
                    json.dump({"resources_base_dir": app_root}, f, indent=4)
                # print(f"Created initial installer_path_config.json at {self.path_config_file}") # Use print before logger is fully setup
            except Exception as e:
                # Fallback to app_root if config file creation fails
                print(f"Error creating initial installer_path_config.json: {e}. Using app root for resources.")
        
        resources_base_dir = app_root # Default base if config fails
        try:
            with open(self.path_config_file, "r") as f:
                config = json.load(f)
                configured_base = config.get("resources_base_dir")
                # Validate the configured path: must be a directory and contain a 'resources' subdir
                # Check for existence of the *potential* resources folder
                if configured_base and os.path.isdir(os.path.join(configured_base, "resources")):
                    resources_base_dir = configured_base
                else:
                    # If configured path is invalid, log and revert to app_root
                    # We can't use self.logger yet, so print.
                    print(f"Warning: Configured resources_base_dir '{configured_base}' in {self.path_config_file} is invalid or missing. Using app root.")
                    # Also update the config file to reflect the valid path
                    self._save_path_config(app_root) 
        except (FileNotFoundError, json.JSONDecodeError) as e:
            # If config file has issues, log and revert to app_root
            print(f"Warning: Error reading installer_path_config.json ({e}). Using app root as default resources base directory.")
            self._save_path_config(app_root) # Recreate/reset if error

        return os.path.join(resources_base_dir, "resources")

    def _save_path_config(self, resources_base_dir):
        """Saves the resources_base_dir to installer_path_config.json."""
        try:
            with open(self.path_config_file, "w") as f:
                json.dump({"resources_base_dir": resources_base_dir}, f, indent=4)
            # Use self.logger if available, otherwise print
            if hasattr(self, 'logger'):
                self.logger.debug(f"Updated resources_base_dir in {self.path_config_file} to: {resources_base_dir}")
            else:
                print(f"DEBUG: Updated resources_base_dir in {self.path_config_file} to: {resources_base_dir}")
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Error saving installer_path_config.json: {e}", exc_info=True)
            else:
                print(f"ERROR: Error saving installer_path_config.json: {e}")


    def _create_dummy_icon(self, path):
        """Creates a dummy icon.png if it doesn't exist, using Pillow."""
        if Image and ImageDraw:
            try:
                img = Image.new('RGB', (32, 32), color=(73, 109, 137))
                d = ImageDraw.Draw(img)
                # Adjust font_size for clearer text on icon
                d.text((8, 5), "G", fill=(255, 255, 255), font_size=20)
                img.save(path)
                self.logger.info(f"Created dummy icon.png at {path}")
            except Exception as e:
                self.logger.warning(f"Failed to create dummy icon.png: {e}. Please ensure Pillow is installed and functional.")
        else:
            self.logger.warning("Pillow not available. Cannot create dummy icon.png.")


    def _setup_logging(self):
        """
        Sets up the custom logging system for the application,
        directing output to console, main log file, and GUI.
        This assumes self.resources_path exists.
        """
        logger = logging.getLogger("GitHubInstaller")
        logger.setLevel(logging.DEBUG)

        # Clear existing handlers to prevent duplicates on potential re-init
        for handler in list(logger.handlers):
            logger.removeHandler(handler)

        # Custom formatter for file and console (detailed)
        formatter = logging.Formatter(
            fmt="[%(asctime)s][%(levelname)s] --- %(message)s --- [%(filename)s - %(funcName)s - %(lineno)d]",
            datefmt="%H:%M:%S"
        )
        # Formatter for GUI (simpler, without full context for readability)
        gui_formatter = logging.Formatter("[%(asctime)s][%(levelname)s] %(message)s", datefmt="%H:%M:%S")

        # File handler for log.log (general log) - Keep a reference to this for closing
        self._main_file_handler = RotatingFileHandler(self.log_file, maxBytes=10*1024*1024, backupCount=5)
        self._main_file_handler.setFormatter(formatter)
        logger.addHandler(self._main_file_handler)

        # Console handler (for debugging if run as .py)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # Custom handler for main GUI text widget
        self.main_gui_log_handler = GUILogHandler(self, lambda msg: self.after(0, self._append_to_log_display, msg))
        self.main_gui_log_handler.setFormatter(gui_formatter)
        logger.addHandler(self.main_gui_log_handler)

        return logger

    def _close_main_log_handlers(self):
        """
        Closes the main log file handlers (`log.log`) to release file locks.
        """
        self.logger.info("Attempting to close main log file handlers to release file locks.")
        if hasattr(self, '_main_file_handler') and self._main_file_handler in self.logger.handlers:
            self.logger.removeHandler(self._main_file_handler)
            self._main_file_handler.close()
            self.logger.info("Main log.log file handler closed.")
        
        # The _log_to_specific_file function already handles adding/removing its handlers per call,
        # so this primarily targets the main log.log handler.


    def _log_to_specific_file(self, level, message, filename, exc_info=None):
        """
        Logs a message to a specific log file in addition to the main log.
        This uses a temporary separate logger and its handler for each call
        to ensure no persistent file locks.
        """
        specific_logger = logging.getLogger(f"SpecificLogger_{os.path.basename(filename)}")
        specific_logger.setLevel(logging.DEBUG)
        
        # Ensure no duplicate handlers for this temporary logger
        for handler in list(specific_logger.handlers):
            specific_logger.removeHandler(handler)

        # Add a new file handler for this specific log file
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
        
        # Crucially, remove and close the handler immediately after logging
        specific_logger.removeHandler(file_handler)
        file_handler.close()


    def _startup_checks(self):
        """
        Performs essential startup checks:
        - Ensures all required log files and data.json exist, recreating them if missing.
        - Synchronizes the app version in data.json with DEFAULT_APP_VERSION.
        - Creates icon.png in resources if missing.
        """
        self.logger.info("Performing startup checks...")
        try:
            # data.json handled here, resources folder assumed to exist from __init__
            if not os.path.exists(self.data_json_file):
                with open(self.data_json_file, "w") as f:
                    json.dump({"github_history": [], "download_dir": os.getcwd(), "current_version": self.DEFAULT_APP_VERSION}, f, indent=4)
                self.logger.info(f"Created missing data.json file: {os.path.basename(self.data_json_file)}")
            else:
                # Synchronize app version
                self._synchronize_app_version()

            # Now, check and create log files using the determined resources_path
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

            # Check and create icon.png in resources folder
            if not os.path.exists(self.icon_path):
                self._create_dummy_icon(self.icon_path)


            self.logger.info("Startup checks complete. All resources are ready.")

            # Append session start header to log.log (main log)
            with open(self.log_file, "a") as f:
                f.write(f"\n{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} --- Application Session Start ---\n")

        except Exception as e:
            self.logger.critical(f"Fatal error during startup checks: {e}", exc_info=True)
            self._log_to_specific_file(logging.CRITICAL, f"Fatal error during startup checks: {e}", self.crash_log_file, exc_info=True)
            messagebox.showerror("Critical Error", f"The application encountered a fatal error during startup and cannot proceed:\n{e}\nCheck crash.log for details.")
            self.destroy() # Close the application if critical files can't be set up

    def _synchronize_app_version(self):
        """
        Reads the version from data.json and updates it to DEFAULT_APP_VERSION
        if they do not match.
        """
        try:
            with open(self.data_json_file, "r+") as f:
                data = json.load(f)
                json_version = data.get("current_version")
                
                if json_version != self.DEFAULT_APP_VERSION:
                    self.logger.info(f"Synchronizing app version: data.json '{json_version}' -> DEFAULT '{self.DEFAULT_APP_VERSION}'")
                    data["current_version"] = self.DEFAULT_APP_VERSION
                    f.seek(0)
                    json.dump(data, f, indent=4)
                    f.truncate()
                    self.app_version = self.DEFAULT_APP_VERSION # Update in-memory version
                else:
                    self.logger.debug(f"App version in data.json ({json_version}) already matches DEFAULT_APP_VERSION ({self.DEFAULT_APP_VERSION}).")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to synchronize app version due to data.json error: {e}. Will use DEFAULT_APP_VERSION.", exc_info=True)
            # If data.json is problematic, _startup_checks will ensure it's created/reset with default version.
        except Exception as e:
            self.logger.critical(f"Unexpected error during version synchronization: {e}", exc_info=True)
            self._log_to_specific_file(logging.CRITICAL, f"Unexpected error during version synchronization: {e}", self.crash_log_file, exc_info=True)


    def _load_version(self):
        """Loads the current version from data.json."""
        try:
            with open(self.data_json_file, "r") as f:
                data = json.load(f)
                # Default to DEFAULT_APP_VERSION if "current_version" key is missing
                version = data.get("current_version", self.DEFAULT_APP_VERSION)
                self.logger.info(f"Loaded application version: {version}")
                return version
        except (FileNotFoundError, json.JSONDecodeError):
            self.logger.warning(f"data.json not found or corrupted during version load. Defaulting to {self.DEFAULT_APP_VERSION}.")
            return self.DEFAULT_APP_VERSION
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while loading version: {e}", exc_info=True)
            return self.DEFAULT_APP_VERSION

    def _save_version(self):
        """Saves the current version to data.json."""
        # This function is implicitly handled by _synchronize_app_version during startup
        # and _save_app_state during shutdown/state changes.
        self.logger.debug("Explicit _save_version called. Version handled by _synchronize_app_version or _save_app_state.")
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
        self.grid_rowconfigure(4, weight=0) # Status bar row
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

        # --- Status Bar ---
        status_frame = ttk.Frame(self, padding="5")
        status_frame.grid(row=4, column=0, padx=10, pady=5, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1) # Progress bar takes most space

        self.progress_var = tk.DoubleVar(value=0)
        self.progressbar = ttk.Progressbar(
            status_frame,
            orient="horizontal",
            length=500,
            mode="determinate",
            variable=self.progress_var
        )
        self.progressbar.grid(row=0, column=0, sticky="ew", padx=5, pady=2)

        self.status_text_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_text_var)
        self.status_label.grid(row=0, column=1, padx=5, pady=2, sticky="e")


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

                # App version is loaded separately by _load_version() and handled in data.json's creation/default

                self.logger.info("Application state loaded.")
        except FileNotFoundError:
            self.logger.warning("data.json not found during app state load. Initializing with default state.")
            # _startup_checks already ensures data.json exists, so this should only happen if deleted mid-run.
            # In that case, saving app state will re-create it.
            self._save_app_state() 
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
            # Ensure resources directory exists before trying to write data.json
            if not os.path.exists(self.resources_path):
                os.makedirs(self.resources_path)
            
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
        """
        Initiates the GitHub content download and installation process in a separate thread.
        """
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

        self.status_text_var.set("Fetching release info...")
        self.progressbar.config(mode="indeterminate")
        self.progressbar.start()

        # Run the actual download logic in a separate thread
        download_thread = threading.Thread(target=self._perform_download_logic, args=(repo_url, download_dir))
        download_thread.daemon = True # Allow the main program to exit even if thread is running
        download_thread.start()


    def _perform_download_logic(self, repo_url, download_dir):
        """
        The actual logic for fetching release info and downloading, run in a separate thread.
        """
        try:
            repo_api_url = repo_url.replace("https://github.com/", "https://api.github.com/repos/")
            # Remove trailing slash if present, then add /releases/latest
            if repo_api_url.endswith('/'):
                repo_api_url = repo_api_url[:-1]
            repo_api_url += "/releases/latest"

            self.logger.info(f"Fetching latest release info from API: {repo_api_url}")
            self.status_text_var.set("Fetching release data...")

            if requests is None:
                self.after(0, lambda: messagebox.showerror("Error", "The 'requests' library is not installed. Cannot download content.\n"
                                     "Please install it using: pip install requests"))
                self.logger.error("Download failed: 'requests' library not found.")
                self.after(0, self._reset_status_bar)
                return

            response = requests.get(repo_api_url, timeout=15)
            
            if response.status_code == 404:
                self.after(0, lambda: messagebox.showerror("Download Error", f"Repository not found or no releases for: {repo_url}"))
                self.logger.error(f"Download failed: 404 Not Found for releases API: {repo_api_url}")
                self.after(0, self._reset_status_bar)
                return
            
            response.raise_for_status() # Raise for other HTTP errors
            release_data = response.json()

            download_url = None
            suggested_filename = None

            # Prioritize zipball_url (source code zip)
            if "zipball_url" in release_data:
                download_url = release_data["zipball_url"]
                # GitHub zipball URL format is like /repos/user/repo/zipball/tag_name
                # We can derive a filename from the repo name and tag.
                repo_name = repo_url.split('/')[-1]
                tag_name = release_data.get("tag_name", "latest").replace("v", "") # Remove 'v' prefix if present
                suggested_filename = f"{repo_name}-{tag_name}.zip"
                self.logger.info(f"Found zipball URL: {download_url}")
            else:
                # Look for a .zip asset in the assets list
                self.logger.info("zipball_url not found. Checking assets for .zip files.")
                for asset in release_data.get("assets", []):
                    if asset.get("name", "").endswith(".zip"):
                        download_url = asset["browser_download_url"]
                        suggested_filename = asset["name"]
                        self.logger.info(f"Found .zip asset: {suggested_filename} at {download_url}")
                        break
            
            if not download_url:
                self.after(0, lambda: messagebox.showerror("Download Error", "No suitable .zip release or asset found for the given repository."))
                self.logger.error(f"No suitable .zip file found for repository: {repo_url}")
                self.after(0, self._reset_status_bar)
                return

            destination_path = os.path.join(download_dir, suggested_filename)
            self.logger.info(f"Starting download of {suggested_filename} to {destination_path}")
            self.status_text_var.set(f"Downloading {suggested_filename}...")
            self.progressbar.config(mode="determinate") # Switch to determinate mode

            self._download_file(download_url, destination_path, self._update_download_progress)
            
            self.logger.info(f"Successfully downloaded {suggested_filename}.")
            self._log_to_specific_file(logging.INFO, f"Downloaded: {suggested_filename}", self.dow_log_file)
            self.after(0, lambda: messagebox.showinfo("Download Complete", f"Successfully downloaded {suggested_filename} to:\n{download_dir}"))
            
            # --- Extraction Logic ---
            if self.extract_on_download_var.get():
                self.logger.info(f"Attempting to extract {suggested_filename}.")
                self.status_text_var.set("Extracting...")
                self.progressbar.config(mode="indeterminate")
                self.progressbar.start()

                # Determine extraction destination based on 'create_folder_on_extract'
                if self.create_folder_on_extract_var.get():
                    extract_folder_name = os.path.splitext(suggested_filename)[0] # Remove .zip
                    final_extract_path = os.path.join(download_dir, extract_folder_name)
                    self.logger.info(f"Creating extraction folder: {final_extract_path}")
                    os.makedirs(final_extract_path, exist_ok=True)
                else:
                    final_extract_path = download_dir
                
                self._extract_zip(destination_path, final_extract_path)

                # --- Delete ZIP after extraction ---
                if self.delete_zip_after_extract_var.get():
                    try:
                        os.remove(destination_path)
                        self.logger.info(f"Deleted downloaded ZIP file: {destination_path}")
                    except Exception as delete_e:
                        self.logger.error(f"Failed to delete ZIP file {destination_path}: {delete_e}", exc_info=True)
                        self.after(0, lambda: messagebox.showwarning("Cleanup Warning", f"Failed to delete downloaded ZIP file:\n{destination_path}\nError: {delete_e}"))

            self.after(0, self._reset_status_bar)
            self.logger.info("Extraction/Installation logic not yet implemented for downloaded content.")
            # Only show this if extraction was NOT done or if there's more to do
            # self.after(0, lambda: messagebox.showinfo("Next Step", "Download complete. Extraction and installation features are coming soon!"))


        except requests.exceptions.RequestException as e:
            self.after(0, lambda: messagebox.showerror("Network Error", f"Could not fetch release info or download file.\nError: {e}"))
            self.logger.error(f"Network error during download logic: {e}", exc_info=True)
            self._log_to_specific_file(logging.ERROR, f"Download failed (network error): {e}", self.crash_log_file, exc_info=True)
            self.after(0, self._reset_status_bar)
        except json.JSONDecodeError:
            self.after(0, lambda: messagebox.showerror("Download Error", "Could not parse GitHub API response. Repository information might be malformed."))
            self.logger.error("JSON decode error during release info fetch.", exc_info=True)
            self._log_to_specific_file(logging.ERROR, "Download failed (JSON parse error).", self.crash_log_file, exc_info=True)
            self.after(0, self._reset_status_bar)
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Unexpected Download Error", f"An unexpected error occurred during download process:\n{e}"))
            self.logger.critical(f"Critical error in download logic: {e}", exc_info=True)
            self._log_to_specific_file(logging.CRITICAL, f"Critical error during download: {e}", self.crash_log_file, exc_info=True)
            self.after(0, self._reset_status_bar)


    def _download_file(self, url, destination_path, progress_callback):
        """
        Downloads a file from a URL to a destination path, providing progress updates.
        """
        self.logger.debug(f"Initiating file download: {url} to {destination_path}")
        try:
            with requests.get(url, stream=True, timeout=60) as r:
                r.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0

                with open(destination_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk: # filter out keep-alive new chunks
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            if total_size > 0:
                                progress = (downloaded_size / total_size) * 100
                                # Use after() to update GUI from different thread
                                self.after(0, progress_callback, progress, downloaded_size, total_size)
            self.logger.debug(f"File download complete: {destination_path}")
        except Exception as e:
            self.logger.error(f"Error during file download: {e}", exc_info=True)
            raise # Re-raise to be caught by _perform_download_logic's outer try/except

    def _update_download_progress(self, progress, downloaded_bytes, total_bytes):
        """Callback to update the GUI progress bar and status label."""
        self.progress_var.set(progress)
        if total_bytes > 0:
            self.status_text_var.set(f"Downloading... {progress:.1f}% ({downloaded_bytes / (1024*1024):.2f}MB / {total_bytes / (1024*1024):.2f}MB)")
        else:
            self.status_text_var.set(f"Downloading... {downloaded_bytes / (1024*1024):.2f}MB")


    def _extract_zip(self, zip_path, destination_path):
        """
        Extracts a ZIP file to the specified destination path.
        Updates status bar during extraction.
        """
        self.logger.info(f"Starting extraction of {os.path.basename(zip_path)} to {destination_path}")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Get list of members to potentially show progress (if needed for large files)
                # For now, just extract directly and use indeterminate progress bar
                zip_ref.extractall(destination_path)
            self.logger.info(f"Successfully extracted {os.path.basename(zip_path)}.")
            self.after(0, lambda: self.status_text_var.set("Extraction Complete."))
        except zipfile.BadZipFile:
            self.logger.error(f"Failed to extract {os.path.basename(zip_path)}: Not a valid ZIP file.", exc_info=True)
            self.after(0, lambda: messagebox.showerror("Extraction Error", f"Failed to extract: '{os.path.basename(zip_path)}' is not a valid ZIP file."))
            self.after(0, lambda: self.status_text_var.set("Extraction Failed."))
            self._log_to_specific_file(logging.ERROR, f"Extraction failed (Bad ZIP file): {os.path.basename(zip_path)}", self.crash_log_file, exc_info=True)
        except Exception as e:
            self.logger.critical(f"Unexpected error during ZIP extraction of {os.path.basename(zip_path)}: {e}", exc_info=True)
            self.after(0, lambda: messagebox.showerror("Extraction Error", f"An unexpected error occurred during extraction:\n{e}"))
            self.after(0, lambda: self.status_text_var.set("Extraction Failed."))
            self._log_to_specific_file(logging.CRITICAL, f"Critical error during extraction: {e}", self.crash_log_file, exc_info=True)


    def _reset_status_bar(self):
        """Resets the status bar to its default state."""
        self.progress_var.set(0)
        self.progressbar.stop()
        self.progressbar.config(mode="determinate") # Reset to default mode
        self.status_text_var.set("Ready")

    # --- Menu Bar Actions ---
    def _move_resources_folder(self):
        """
        Prompts the user to select a new location for the 'resources' folder,
        moves it, updates the path configuration, and restarts the application.
        """
        self.logger.info("Initiating 'Move resources folder' process.")
        new_parent_dir = filedialog.askdirectory(
            initialdir=os.path.dirname(self.resources_path),
            title="Select New Location for Resources Folder"
        )
        
        if not new_parent_dir:
            self.logger.info("Move resources folder cancelled by user.")
            return

        current_resources_path = self.resources_path
        new_resources_path = os.path.join(new_parent_dir, "resources")

        # Prevent moving into a subdirectory of itself
        # Convert to real paths to handle symlinks/junctions, though os.path.commonpath is usually sufficient
        real_current_path = os.path.realpath(current_resources_path)
        real_new_path = os.path.realpath(new_resources_path)
        
        if real_current_path == real_new_path:
            messagebox.showinfo("No Change", "Resources folder is already at the selected location.")
            self.logger.info("Resources folder already at selected location, no move needed.")
            return

        # Check if new_resources_path is a sub-path of current_resources_path
        if os.path.commonpath([real_current_path, real_new_path]) == real_current_path:
             messagebox.showerror("Error", "Cannot move resources folder into itself or its subdirectories.")
             self.logger.error(f"Attempted to move resources into a subdirectory of itself: {real_new_path}")
             return


        if not messagebox.askyesno(
            "Confirm Move and Restart",
            f"Are you sure you want to move the 'resources' folder from:\n\n"
            f"'{current_resources_path}'\n\nTO:\n\n'{new_resources_path}'\n\n"
            f"The application will restart after the move."
        ):
            self.logger.info("Move resources folder cancelled by user confirmation.")
            return

        try:
            # 1. Close all active log file handlers to release file locks
            self._close_main_log_handlers()
            # Note: _log_to_specific_file uses temporary handlers, so no need to close them here.

            # 2. Update the path config file *before* moving the resources folder
            # This is crucial so that the restarted app knows where to look.
            self._save_path_config(new_parent_dir)
            self.logger.info(f"Updated installer_path_config.json with new resources base: {new_parent_dir}")

            # 3. Now, move the folder
            shutil.move(current_resources_path, new_resources_path)
            self.logger.info(f"Successfully moved resources folder from '{current_resources_path}' to '{new_resources_path}'.")
            messagebox.showinfo("Move Complete", "Resources folder moved successfully. The application will now restart.")
            self._restart_application()

        except shutil.Error as e:
            # If shutil.move fails, revert path config and re-initialize logging
            messagebox.showerror("Move Error", f"Error moving resources folder:\n{e}\nCheck permissions or if the folder is in use.")
            self.logger.error(f"Shutil error moving resources folder: {e}", exc_info=True)
            # Revert path config if move failed to original parent directory
            self._save_path_config(os.path.dirname(current_resources_path)) 
            # Re-setup logging since handlers were closed and move failed
            self.logger = self._setup_logging() 
        except Exception as e:
            # Catch other unexpected errors during the move process
            messagebox.showerror("Unexpected Error", f"An unexpected error occurred during move:\n{e}")
            self.logger.critical(f"Critical error during resources folder move: {e}", exc_info=True)
            self._log_to_specific_file(logging.CRITICAL, f"Critical error during resources folder move: {e}", self.crash_log_file, exc_info=True)
            # Revert path config if move failed
            self._save_path_config(os.path.dirname(current_resources_path))
            # Re-setup logging if move failed
            self.logger = self._setup_logging()


    def _restart_application(self):
        """
        Restarts the current application instance.
        On Windows, uses a temporary batch script for robustness against file locking.
        """
        self.logger.info("Preparing to restart application...")
        python_exe = sys.executable
        current_script = os.path.abspath(sys.argv[0]) # Path to the current running .pyw script

        if sys.platform == "win32":
            # Create a temporary batch script to wait for current app to exit, then restart
            temp_bat_path = os.path.join(tempfile.gettempdir(), "restart_installer.bat")
            with open(temp_bat_path, "w") as f:
                f.write(f'@echo off\n')
                f.write(f'timeout /t 1 /nobreak > nul\n') # Wait 1 second for current app to fully close
                f.write(f'start "" "{python_exe}" "{current_script}"\n')
                f.write(f'del "{temp_bat_path}"\n') # Delete the temp batch file
            subprocess.Popen(temp_bat_path, shell=True)
        else: # For macOS/Linux (assuming a shebang or direct python execution)
            # For .pyw like behavior, Popen without shell=True is usually preferred.
            subprocess.Popen([python_exe, current_script])
        
        self.destroy() # Close the current application instance
        sys.exit(0) # Exit the current process


    def _update_installer(self):
        """
        Checks for a newer version of the installer on GitHub.
        If a newer version is found, it downloads it and initiates a self-replacement.
        """
        self.logger.info("Checking for installer updates...")
        if requests is None:
            messagebox.showerror("Error", "The 'requests' library is not installed. Cannot check for updates.\n"
                                 "Please install it using: pip install requests")
            self.logger.error("Update check failed: 'requests' library not found.")
            return

        try:
            # First, check for latest release version
            response = requests.get(self.GITHUB_REPO_FOR_UPDATES_API, timeout=10)
            
            # Check specifically for 404, which means no releases found
            if response.status_code == 404:
                messagebox.showinfo(
                    "Update Check",
                    "No official releases found for the installer repository on GitHub. "
                    "The developer may not have published any releases yet, or the repository URL is incorrect.\n\n"
                    f"Repository API checked: {self.GITHUB_REPO_FOR_UPDATES_API.replace('/releases/latest', '')}"
                )
                self.logger.warning(f"Update check failed: 404 Not Found, likely no releases for {self.GITHUB_REPO_FOR_UPDATES_API}")
                return

            response.raise_for_status() # Raise for other HTTP errors (e.g., 500, permissions)
            latest_release = response.json()
            
            latest_tag_name = latest_release.get("tag_name")
            if not latest_tag_name:
                self.logger.warning("Could not find 'tag_name' in latest GitHub release data. Response might be malformed or empty.")
                messagebox.showinfo("Update Check", "Could not determine latest version from GitHub API response. Please check manually.")
                return

            self.logger.info(f"Latest online version: {latest_tag_name}, Current version: {self.app_version}")

            # Simple string comparison for version. For robust comparison (e.g., v1.0.0 vs v1.0.10)
            # consider installing 'packaging' library: pip install packaging
            # from packaging.version import parse as parse_version
            # if parse_version(latest_tag_name) > parse_version(self.app_version):
            if latest_tag_name > self.app_version: 
                if messagebox.askyesno(
                    "Update Available!",
                    f"A new version of the installer is available: {latest_tag_name}\n\n"
                    f"Your current version: {self.app_version}\n\n"
                    "Would you like to download and install the update now? "
                    "The application will restart."
                ):
                    self._download_and_replace_installer(self.GITHUB_RAW_PYW_URL)
                else:
                    self.logger.info("User declined to update.")
            else:
                messagebox.showinfo("No Updates", f"You are running the latest version: {self.app_version}")
                self.logger.info("No newer version found.")

        except requests.exceptions.RequestException as e:
            messagebox.showerror("Network Error", f"Could not check for updates. Please check your internet connection.\nError: {e}")
            self.logger.error(f"Network error during update check: {e}", exc_info=True)
        except json.JSONDecodeError:
            messagebox.showerror("Update Error", "Could not parse update information. GitHub API response might be malformed.")
            self.logger.error("JSON decode error during update check.", exc_info=True)
        except Exception as e:
            messagebox.showerror("Unexpected Error", f"An unexpected error occurred during update check:\n{e}")
            self.logger.critical(f"Critical error during update check: {e}", exc_info=True)
            self._log_to_specific_file(logging.CRITICAL, f"Critical error during update check: {e}", self.crash_log_file, exc_info=True)

    def _download_and_replace_installer(self, download_url):
        """
        Downloads the new installer file and prepares for self-replacement.
        This closes the current app and launches a helper script to do the replacement.
        """
        self.logger.info(f"Downloading new installer from: {download_url}")
        try:
            response = requests.get(download_url, stream=True, timeout=30)
            response.raise_for_status()

            # Create a temporary file to save the new installer
            temp_dir = tempfile.mkdtemp()
            new_installer_path = os.path.join(temp_dir, self.INSTALLER_FILENAME)

            with open(new_installer_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.logger.info(f"New installer downloaded to: {new_installer_path}")
            messagebox.showinfo("Update Downloaded", "New installer downloaded. Preparing to replace and restart.")

            # Initiate the replacement script and exit
            self._initiate_self_replacement(new_installer_path)

        except requests.exceptions.RequestException as e:
            messagebox.showerror("Download Error", f"Failed to download update: {e}")
            self.logger.error(f"Error downloading new installer: {e}", exc_info=True)
        except Exception as e:
            messagebox.showerror("Update Error", f"An unexpected error occurred during update download: {e}")
            self.logger.critical(f"Critical error during update download: {e}", exc_info=True)
            self._log_to_specific_file(logging.CRITICAL, f"Critical error during update download: {e}", self.crash_log_file, exc_info=True)

    def _initiate_self_replacement(self, new_installer_path):
        """
        Creates a temporary script to perform the self-replacement and restart,
        then exits the current application.
        """
        current_installer_path = os.path.abspath(sys.argv[0])
        old_installer_backup_path = current_installer_path + ".old" # For a quick backup

        self.logger.info("Initiating self-replacement sequence...")
        
        # Ensure log handlers are closed before the replacement to avoid file locks
        self._close_main_log_handlers()

        if sys.platform == "win32":
            temp_script_name = "updater_script.bat"
            temp_script_path = os.path.join(tempfile.gettempdir(), temp_script_name)
            
            with open(temp_script_path, "w") as f:
                f.write(f'@echo off\n')
                f.write(f'echo Waiting for current installer to close...\n')
                f.write(f'timeout /t 2 /nobreak > nul\n') # Wait 2 seconds for app to fully close
                
                f.write(f'echo Attempting to replace installer...\n')
                # Optional: Delete old backup if it exists
                f.write(f'if exist "{old_installer_backup_path}" del "{old_installer_backup_path}"\n')
                # Rename current installer to .old
                f.write(f'rename "{current_installer_path}" "{os.path.basename(old_installer_backup_path)}"\n')
                # Move new installer to current location
                f.write(f'move /y "{new_installer_path}" "{current_installer_path}"\n')
                
                f.write(f'if exist "{current_installer_path}" (\n')
                f.write(f'    echo Update complete. Restarting installer...\n')
                f.write(f'    start "" "{sys.executable}" "{current_installer_path}"\n')
                f.write(f') else (\n')
                f.write(f'    echo Error: Failed to replace installer. Check permissions.\n')
                f.write(f'    pause\n') # Keep window open to show error
                f.write(f')\n')
                f.write(f'del "{temp_script_path}"\n') # Delete this batch script
                f.write(f'exit\n') # Exit the batch script
            
            subprocess.Popen(temp_script_path, shell=True)
        else:
            # For macOS/Linux, a similar shell script or direct os.rename/shutil.move after closing
            # would be needed. This is a simplified placeholder for non-Windows.
            self.logger.warning("Automated self-replacement on non-Windows platforms is not fully implemented for robustness. Manual replacement may be needed.")
            # Basic attempt for non-Windows (still risky with file locks)
            try:
                # Assuming handlers are already closed by previous call
                os.rename(current_installer_path, old_installer_backup_path)
                shutil.move(new_installer_path, current_installer_path)
                self.logger.info("Replacement attempted. Restarting.")
                subprocess.Popen([sys.executable, current_installer_path])
            except Exception as e:
                self.logger.critical(f"Critical error during non-Windows self-replacement: {e}", exc_info=True)
                messagebox.showerror("Update Error", f"Failed to perform automated update. Please replace '{self.INSTALLER_FILENAME}' manually.\nError: {e}")
            
        self.destroy() # Close the current application
        sys.exit(0) # Exit the current process


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
        self.developer_console_window.grab_set() # Make it modal
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

        self.developer_console_window.wait_window(self.developer_console_window)


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
