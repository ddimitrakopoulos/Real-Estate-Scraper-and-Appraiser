#import the needed libraries for the script
import pandas as pd
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import csv
from webdriver_manager.chrome import ChromeDriverManager
import threading
import re
import time
import xlsxwriter

#this is the function that breaks up the excel file into the nuisance, nuisance_board_up and unsafe_structure CSVs
def process_file(file_path):
    #save the files in the data folder inside this directory
    os.makedirs("data", exist_ok=True)

    # Read the Excel file, skipping the first 6 rows that are the picture
    df = pd.read_excel(file_path, skiprows=6)

    # Normalize column names
    df.columns = df.columns.str.strip()

    # Define expected column names that we use in order to strip the desired pin numbers
    code_section_col = "Code Section"
    re_number_col = "RE Number"

    # Ensure required columns exist
    if code_section_col not in df.columns or re_number_col not in df.columns:
        messagebox.showerror("Error", "One or both expected columns ('Code Section', 'RE Number') are missing!")
        return None

    # Fill down missing values in "Code Section" because the code section only appears once per section
    #and not in each specific row
    df[code_section_col] = df[code_section_col].ffill()

    # Rename "RE Number" to "DocLegalDescription" in order for the other function to understand that
    # this is the section that refferes to PIN numbers for the properties
    df = df.rename(columns={re_number_col: "DocLegalDescription"})

    # Define categories and output filenames
    categories = {
        "Nuisance": "data/nuisance.csv",
        "Nuisance Board Up": "data/nuisance_board_up.csv",
        "Unsafe Structure": "data/unsafe_structure.csv"
    }

    output_files = {}
    for category, filename in categories.items():
        #get each pin for each category
        filtered_rows = df[df[code_section_col].str.strip().eq(category)]
        #drop any duplicates
        doc_legal_desc = filtered_rows[["DocLegalDescription"]].dropna().drop_duplicates()
        #write PIN + pin-number
        doc_legal_desc["DocLegalDescription"] = "PIN " + doc_legal_desc["DocLegalDescription"].astype(str)

        # Save to CSV with unique values
        doc_legal_desc.to_csv(filename, index=False)
        output_files[category] = filename

    return output_files

# Web scraping function for loading the wordlist.txt
def load_wordlist(filepath="data/wordlist.txt"):
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            return [line.strip() for line in file if line.strip()]
    except FileNotFoundError:
        return []

#function using regular expression to check if a string is inside a word
#used mainly to check if anything in the wordlist is also in the scraped name, in order to
#detect if it is a business or person
def is_company(text, wordlist):
    pattern = r'\b(?:' + '|'.join(map(re.escape, wordlist)) + r')\b'
    return bool(re.search(pattern, text, re.IGNORECASE)) or "LLC" in text.upper()

#used to break up a scraped row into property address, zip and state
def parse_address_v1(address):
    match = re.match(r"(.+?)\s([A-Z]{2})\s(\d+)-?", address)
    if match:
        city, state, zip_code = match.groups()
        return city, state, zip_code
    return None

#used to break up a scraped row into mailing address, zip and state
def parse_address_v2(address):
    match = re.match(r"(.+),\s([A-Z]{2})\s(\d+)", address)
    if match:
        city, state, zip_code = match.groups()
        return city, state, zip_code
    return None

#used to break up row into first and last name
def get_first_last_name(text):
    words = text.split()
    last_name = words[0] if len(words) > 0 else ""
    first_name = words[1] if len(words) > 1 else ""
    return first_name, last_name

#gets the input csv and makes the list of urls depending on the pins
def make_urls(input_csv):
    with open(input_csv, mode='r', newline='', encoding='utf-8') as file:
        reader = list(csv.reader(file))
        header = reader[0]
        if "DocLegalDescription" not in header:
            raise ValueError("Column 'DocLegalDescription' not found in the CSV file.")
        col_index = header.index("DocLegalDescription")
        pin_values = [row[col_index] for row in reader[2:] if len(row) > col_index and row[col_index].startswith("PIN")]
    pattern = re.compile(r'(\d{6})[-\s]+(\d{4})')
    extracted_urls = ["https://paopropertysearch.coj.net/Basic/Detail.aspx?RE=" + match.group(1) + match.group(2)
                      for value in pin_values if (match := pattern.search(value))]
    return extracted_urls

#the function to scrape a url from paopropertysearch
#get the wordlist, the url and the webdriver
def extract_data(url, wordlist, driver):
    #open the given url
    driver.get(url)
    #function to get text from an element if it exists, else return "Not found"
    def get_text(xpath):
        element = driver.find_elements("xpath", xpath)
        return element[0].text if element else "Not found"
    #get owner name
    owner_name = get_text('//span[contains(@id,"ctl00_cphBody_repeaterOwnerInformation_ctl00_lblOwnerName")]')
    #get mailing address
    mailing_address = get_text('//span[contains(@id,"ctl00_cphBody_repeaterOwnerInformation_ctl00_lblMailingAddressLine1")]')
    notes = ""
    #if c/o is in the mailing address then make the notes = mailing address
    #and set the mailing address as the second row
    if ("C/O" in mailing_address) or ("C/0" in mailing_address):
        notes = mailing_address
        mailing_address = get_text('//span[contains(@id,"ctl00_cphBody_repeaterOwnerInformation_ctl00_lblMailingAddressLine2")]')
    #if not then try to get the second line as notes, but keep them only if they are not empty
    else:
        notes = get_text('//span[contains(@id,"ctl00_cphBody_repeaterOwnerInformation_ctl00_lblMailingAddressLine2")]')
    if notes == "Not found":
        notes = ""
    #get mailing_city_info
    mailing_city_info = get_text('//span[contains(@id,"ctl00_cphBody_repeaterOwnerInformation_ctl00_lblMailingAddressLine3")]')
    #get property_address
    property_address = get_text('//span[contains(@id,"ctl00_cphBody_lblPrimarySiteAddressLine1")]')
    #get property_city_info
    property_city_info = get_text('//span[contains(@id,"ctl00_cphBody_lblPrimarySiteAddressLine2")]')
    #get re number
    re_number = get_text('//span[contains(@id,"ctl00_cphBody_lblRealEstateNumber")]')
    #get property_use
    property_use = get_text('//span[contains(@id,"ctl00_cphBody_lblPropertyUse")]')
    #try to find the table that contains the zoning info , if it doesn't exist return Not found
    try:
        table = driver.find_element(By.ID, "ctl00_cphBody_gridLand")
        rows = table.find_elements(By.TAG_NAME, "tr")
        second_row_columns = rows[1].find_elements(By.TAG_NAME, "td")
        zoning = second_row_columns[3].text
    except:
        zoning = "Not found"

    business_name, first_name, last_name = "", "", ""
    #split up mailing info into state, zip and address
    try:
        mailing_city, mailing_state, mailing_zip = parse_address_v2(mailing_city_info)
    except:
        mailing_city = mailing_state = mailing_zip = ""

    #split up property info into state, zip and address
    try:
        property_city, property_state, property_zip = parse_address_v1(property_city_info)
    except:
        property_city = property_state = property_zip = ""
    #get first and last name if it is not a company
    try:
        business_name = owner_name
        if (not is_company(owner_name, wordlist)):
            first_name, last_name = get_first_last_name(owner_name)
    except Exception as e:
        print("Error:", e)

    return [business_name, first_name, last_name, mailing_address, mailing_city, mailing_state, mailing_zip,
            property_address, property_city, property_state, property_zip, url, re_number, property_use, zoning, notes]

#make the headless webdriver and scrape the urls
def start_scraping(input_csv, stop_flag, progress_var, progress_label, status_label, total_urls, progress_step):
    #webdriver options
    options = Options()
    options.add_argument('--headless')
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    #get the urls and write the first row of the excel output
    url_list = make_urls(input_csv)
    file_path = 'business_info.xlsx'
    workbook = xlsxwriter.Workbook(file_path)
    worksheet = workbook.add_worksheet('Business Info')

    headers = [
        "Business_name", "first_name", "last_name", "mailing_address", "mailing_city", "mailing_state", "mailing_zip",
        "property_address", "property_city", "property_state", "property_zip", "link", "RE #", "Property use", "Zoning Assesment", "Notes"
    ]
    worksheet.write_row(0, 0, headers)

    wordlist = load_wordlist()
    x_all = len(url_list)
    #scrape the urls and update the progress bar
    try:
        for index, url in enumerate(url_list, start=1):
            if stop_flag[0]:
                print("Scraping stopped by user.")
                status_label.config(text="Stopped", fg="red")
                break
            data = extract_data(url, wordlist, driver)
            worksheet.write_row(index, 0, data)
            print(f"{url} - {index} out of {x_all}")

            progress_var.set(index * progress_step)
            progress_label.config(text=f"{index} out of {x_all}")
            status_label.config(text="Running", fg="green")
            root.update_idletasks()
    except Exception as e:
        print(f"An error occurred: {e}")
    #save the excel file
    driver.quit()
    workbook.close()
    print("Scraping completed and Excel file created!")
    status_label.config(text="Stopped", fg="red")

#upload file for the nuisance, nuisance_board_up and unsafe_structure CSVs
def upload_file(status_label):
    file_path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
    if not file_path:
        return

    status_label.config(text="Processing file...")
    output_files = process_file(file_path)

    if output_files:
        status_label.config(text="Processing completed! Download files from 'data' folder.")
        messagebox.showinfo("Success", "CSV files have been generated successfully!")
    else:
        status_label.config(text="Processing failed.")

#select file for the scraping
def select_file_for_scraping():
    file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
    return file_path

#function to download the LIEN csv
def download_data():
    #save in the data folder in this directory
    download_folder = os.path.join(os.getcwd(), "data")
    #webdriver options
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_experimental_option("detach", True)
    options.add_argument('--headless')
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # Set download preferences for Chrome
    prefs = {
        "download.default_directory": download_folder,  # Set the download directory
        "download.prompt_for_download": False,  # Disable the download prompt
        "directory_upgrade": True
    }

    options.add_experimental_option("prefs", prefs)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    #open duval clerk
    driver.get("https://or.duvalclerk.com/Search/Disclaimer?st=/search/SearchTypeDocType")
    #accept the conditions
    submit_button = driver.find_element(By.ID, "btnButton")
    submit_button.click()
    #click DocTypesDisplay
    input_field = driver.find_element(By.ID, "DocTypesDisplay-input")
    input_field.clear()  # Clear the field in case there is any default value

    # Write "LIEN (LN)" into the input field
    input_field.send_keys("LIEN (LN)")

    # Find the span element by its text and click it
    span_element = driver.find_element(By.XPATH, "//span[contains(text(),'Specify Date Range...')]")
    span_element.click()

    # Wait for the dropdown to appear
    time.sleep(1)  # Adjust timing if necessary

    # Find the li element by its text and click the Last 90 Days option
    li_element = driver.find_element(By.XPATH, "//li[contains(text(),'Last 90 Days')]")
    li_element.click()
    time.sleep(1)
    #submit these parameters
    submit_button2 = driver.find_element(By.ID, "btnSearch")
    submit_button2.click()
    time.sleep(3)
    #find the input field
    input_element = driver.find_element(By.ID, "fldText")
    input_element.clear()  # Clear the field if there is any pre-filled text
    # Write "Jacksonville city of" into the input field
    input_element.send_keys("Jacksonville city of")
    #Find search button and click it
    button_elements = driver.find_elements(By.CLASS_NAME, "t-button")
    button_elements[4].click()
    time.sleep(1)
    #click download button
    button_elements[12].click()
    print(f"File should have been downloaded to: {download_folder}")

#all the code for the gui
def run_gui():
    #this flag is to stop the scraping if you press the stop button
    stop_flag = [False]

    #when the start button is press the stop flag is zero and we summon the progress bar and update it
    #also run the scraping script
    def on_start_button_click():
        stop_flag[0] = False
        input_csv = select_file_for_scraping()

        if input_csv:
            total_urls = len(make_urls(input_csv))
            progress_step = 100 / total_urls if total_urls > 0 else 100

            threading.Thread(target=start_scraping, args=(input_csv, stop_flag, progress_var, progress_label, status_label, total_urls, progress_step)).start()

    #pressinf stop make the flag true
    def on_stop_button_click():
        stop_flag[0] = True

    #pressing download sends the text and starts the download
    def on_download_button_click():
        status_label.config(text="Started the download...")
        threading.Thread(target=download_data).start()

    global root
    root = tk.Tk()
    #title
    root.title("Housing Scraper")

    #text
    title_label = tk.Label(root, text="   Real Estate Scraper and Appraiser   ", font=("Arial", 14))
    title_label.pack(pady=10)
    #first button
    upload_button = tk.Button(root, text="Upload Excel File", command=lambda: upload_file(status_label), font=("Arial", 12))
    upload_button.pack(pady=5)
    #button
    scraping_button = tk.Button(root, text="Start Scraping", command=on_start_button_click, font=("Arial", 12))
    scraping_button.pack(pady=5)
    #button
    stop_button = tk.Button(root, text="Stop Scraping", command=on_stop_button_click, font=("Arial", 12))
    stop_button.pack(pady=5)
    #button
    download_button = tk.Button(root, text="Download LIEN Data", command=on_download_button_click, font=("Arial", 12))
    download_button.pack(pady=5)
    #button
    status_label = tk.Label(root, text="", fg="blue", font=("Arial", 10))
    status_label.pack(pady=10)
    #progress bar
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=100)
    progress_bar.pack(padx=10, pady=10, fill=tk.X)
    #text for progress bar
    progress_label = tk.Label(root, text="0 out of 0")
    progress_label.pack(padx=10, pady=10)
    #exit button
    exit_button = tk.Button(root, text="Exit", command=root.quit, font=("Arial", 12))
    exit_button.pack(pady=10)

    root.mainloop()


if __name__ == "__main__":
    run_gui()
