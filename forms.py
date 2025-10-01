from web_automation import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = webdriver.Chrome()
driver.get("https://oneworldrental.com/general_inquiry")

# Fill out the form
driver.find_element(By.ID, "name_home").send_keys("Talha Iftikhar")
driver.find_element(By.ID, "email_home").send_keys("talha@example.com")
driver.find_element(By.ID, "phone_home").send_keys("03001234567")
driver.find_element(By.ID, "company_home").send_keys("OWR")
driver.find_element(By.ID, "location_home").send_keys("Islamabad")

# Select checkboxes
driver.find_element(By.ID, "ipad-tablet").click()
driver.find_element(By.ID, "laptops").click()

# Fill other fields
driver.find_element(By.ID, "otherstate2_home").send_keys("Custom Device")
driver.find_element(By.ID, "tellusmore_home").send_keys("Need devices for a tech event.")

# Submit the form
driver.find_element(By.ID, "submitBtn_home").click()

# Wait for success message
try:
    success = WebDriverWait(driver, 10).until(
        EC.visibility_of_element_located((By.ID, "success_message"))
    )
    print("Form submitted successfully:", success.text)
except:
    print("Form submission failed or CAPTCHA blocked it.")

driver.quit()
