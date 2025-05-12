import streamlit as st
import os
import base64
import json
import re
from pathlib import Path
import google.generativeai as genai
from github import Github, RateLimitExceededException, UnknownObjectException
import time
import io

# --- Page configuration ---
st.set_page_config(page_title="ByeResume - Ayushman Tomar", layout="wide")

# --- App title and description ---
st.title("Resume & GitHub Job Match Analyzer")
st.markdown("""
This app analyzes your GitHub projects and resume against job descriptions to provide:
1. Skills to highlight for better selection chances
2. Projects to mention with ready-to-paste content
3. An updated objective statement for your resume
4. Tips for interview preparation
""")

# --- Global variable to store uploaded file content ---
# Using session state is generally preferred for keeping state across reruns
if 'uploaded_resume_content' not in st.session_state:
    st.session_state.uploaded_resume_content = None
if 'uploaded_resume_filename' not in st.session_state:
    st.session_state.uploaded_resume_filename = None

# --- Function to fetch repositories from GitHub ---
def fetch_github_repos(username, github_token_from_input=None):
    """
    Fetches GitHub repositories for a given username using authentication if available.
    Includes name, description, and README content. Only fetches non-forked repositories.
    Priority for token: Input field > Streamlit secrets > Environment variable.
    """
    github_token = github_token_from_input # Prioritize token from input field

    if not github_token:
        try:
            if "GITHUB_TOKEN" in st.secrets:
                github_token = st.secrets["GITHUB_TOKEN"]
        except Exception:
            pass # st.secrets might not exist

    if not github_token:
        github_token = os.environ.get("GITHUB_TOKEN")

    try:
        if github_token:
            g = Github(github_token)
        else:
            g = Github()
            st.sidebar.warning(
                "No GitHub token provided (checked input, secrets & env var). "
                "Using unauthenticated access (low rate limits: ~60/hr). "
                "May hit 'Rate Limit Exceeded'. Add a token for higher limits.", icon="⚠️"
            )
            rate_limit_info = g.get_rate_limit()
            st.sidebar.caption(f"GitHub API (Unauth): {rate_limit_info.core.remaining}/{rate_limit_info.core.limit} requests remaining.")

        user = g.get_user(username)
        repos = user.get_repos(sort="updated", direction="desc")

        repo_data = []
        processed_count = 0
        max_repos_to_process = 50

        for repo in repos:
            if not repo.fork:
                if processed_count >= max_repos_to_process:
                    st.sidebar.info(f"Stopped fetching after processing {max_repos_to_process} non-forked repos to manage API usage.")
                    break

                readme_content = ""
                try:
                    readme = repo.get_readme()
                    readme_bytes = base64.b64decode(readme.content)
                    readme_content = readme_bytes.decode('utf-8', errors='ignore')
                except UnknownObjectException:
                    pass # README not found
                except Exception:
                    pass # Other errors decoding/fetching readme

                repo_info = {
                    "name": repo.name,
                    "description": repo.description or "No description provided.",
                    "readme": readme_content[:8000] if readme_content else "" # Limit readme size
                }
                repo_data.append(repo_info)
                processed_count += 1

        if not repo_data and processed_count == 0:
             st.sidebar.warning(f"No non-forked public repositories found for user '{username}'.") # Use sidebar warning for fetch info
        return repo_data

    except RateLimitExceededException:
        st.error(f"GitHub API Rate Limit Exceeded. Please wait a while before trying again.")
        if not github_token:
            st.error("Consider adding a GitHub Personal Access Token to significantly increase the rate limit.")
        return []
    except UnknownObjectException:
         st.error(f"GitHub user '{username}' not found. Please check the username.")
         return []
    except Exception as e:
        st.error(f"An unexpected error occurred while fetching GitHub repositories: {type(e).__name__} - {str(e)}")
        return []

# --- Function to get resume content (MODIFIED) ---
def get_resume_content():
    """
    Gets resume content. Only uses uploaded files, no local file reading.
    Returns the content as a string and the source ('upload' or 'none').
    """
    # Check session state for content from an uploaded file
    if st.session_state.uploaded_resume_content:
        return st.session_state.uploaded_resume_content, "upload"
    else:
        # No uploaded file in session state
        return "", "none"

# --- Function to analyze with Gemini API ---
def analyze_with_gemini(github_data, resume_text, job_description, role, company):
    """Sends data to Gemini API for analysis and returns the response text."""
    try:
        api_key = st.session_state.get("gemini_api_key")
        if not api_key:
            st.error("Gemini API key is missing. Please add it in the sidebar.")
            return "Error: Gemini API key is missing."

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest', generation_config={"temperature": 0.1})

        prompt = f"""
        ## Task: Provide detailed job application optimization based on resume, GitHub projects, and job description

        You are an AI assistant specialized in resume optimization and job application strategy. Analyze the provided resume content, GitHub project information (limited to name, description, and README), and job description to provide highly relevant and actionable advice.

        ### Resume Content:
        ```
        {resume_text}
        ```

        ### GitHub Projects (Name, Description, and README excerpts):
        ```json
        {json.dumps(github_data, indent=2)}
        ```

        ### Job Details:
        - Position: {role}
        - Company: {company}
        - Job Description:
        ```
        {job_description}
        ```

        ### Instructions:
        Based *only* on the provided content (resume, GitHub data, job description), generate the following sections. Ensure the suggested skills and projects are directly supported by the resume or the GitHub data provided.
        Format the output clearly using **Bolded Section Titles with Numbering** as shown below. Include a brief introductory sentence for sections 1, 2, and 4 if appropriate.

        **1. Skills to Highlight**
        [Introductory sentence]
        *   Skill Name: Explanation linking to job description and source (resume/github)

        **2. Projects to Showcase**
        [Introductory sentence]
        *   **Project Name**: Professional description (approx. 100-150 words) highlighting relevance to the job.

        **3. Resume Objective**
        [Compelling objective statement, 3-4 sentences.]

        **4. Interview Preparation Tips**
        [Introductory sentence]
        *   **Technical/Domain Areas to Review:** List specific areas based on job/background.
        *   **Example Interview Questions:** List relevant questions.
        *   **Strategic Advice:** Offer tips for discussing experience.

        Do not include any information not present in the provided inputs. Do not add extra sections or formatting not requested.
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Error analyzing with Gemini: {type(e).__name__} - {str(e)}")
        if "API key not valid" in str(e):
            st.error("Invalid Gemini API Key. Please check the key in the sidebar.")
        elif "quota" in str(e).lower():
             st.error("Quota exceeded for Gemini API. Check your usage limits or try again later.")
        elif "blocked" in str(e).lower():
             st.error("Content was blocked by the Gemini API safety filters. Please review inputs.")
        return f"An error occurred during Gemini analysis: {str(e)}"

# --- Function to display results ---
def display_results(analysis_text):
    """Parses and displays the analysis text from Gemini."""
    def extract_section(text, section_name):
        pattern = rf"(?:^|\n)\s*\*\*(\d+\.\s+)?{re.escape(section_name)}\*\*(.*?)(?=\n\s*\*\*(\d+\.\s+)?.*?\*\*|\Z)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            content = match.group(2).strip()
            if not content or content.startswith("**"):
                 return None
            return content
        return None

    st.subheader("📊 Analysis Results")
    sections_found_count = 0

    sections_to_display = {
        "Skills to Highlight": True,
        "Projects to Showcase": True,
        "Resume Objective": True,
        "Interview Preparation Tips": True
    }

    if analysis_text.startswith("Error:") or "An error occurred during Gemini analysis:" in analysis_text:
         st.error("Analysis failed: " + analysis_text)
         return

    for section_title, expanded_default in sections_to_display.items():
        section_content = extract_section(analysis_text, section_title)
        with st.expander(section_title, expanded=expanded_default):
            if section_content:
                st.markdown(section_content)
                sections_found_count +=1
                if section_title == "Resume Objective":
                    st.text_area("Copy-paste ready objective:", section_content, height=100, key=f"copy_{section_title.lower().replace(' ', '_')}")
            else:
                st.warning(f"Could not extract '{section_title}' section from the AI response. Check the raw response below for formatting issues.")

    if sections_found_count == 0 and analysis_text and not analysis_text.startswith("Error:"):
        st.warning("Could not parse structured sections from the AI response. Displaying raw response below:")
        with st.expander("Show Raw Gemini Response (Parsing Failed)", expanded=True):
            st.text_area("Raw Response", analysis_text, height=300, key="raw_response_fallback_display")
    elif analysis_text:
         with st.expander("Show Raw Gemini Response", expanded=False):
             st.text_area("Raw Response from AI", analysis_text, height=300, key="raw_response_main_display")

# --- Sidebar for configuration ---
with st.sidebar:
    st.header("🔑 API Keys & Settings")

    # Gemini API Key
    if 'gemini_api_key' not in st.session_state:
        st.session_state.gemini_api_key = ""
    st.session_state.gemini_api_key = st.text_input(
        "Gemini API Key",
        value=st.session_state.gemini_api_key,
        type="password",
        help="Get your API key from [Google AI Studio](https://makersuite.google.com/)"
    )

    # GitHub Token Input
    if 'github_pat' not in st.session_state:
        st.session_state.github_pat = ""
    st.session_state.github_pat = st.text_input(
        "GitHub Personal Access Token (Optional)",
        value=st.session_state.github_pat,
        type="password",
        help="For higher API rate limits. Generate a PAT with 'public_repo' scope from GitHub Developer Settings."
    )
    st.caption("If no token provided here, checks secrets/env vars, then uses unauthenticated access.")

    st.divider()
    st.header("👤 User Information")
    # GitHub Username
    github_username_input = st.text_input(
        "GitHub Username",
        st.session_state.get("github_username", ""), # Start empty or use default if preferred
        help="Enter your GitHub username to fetch public repositories"
    )
    if github_username_input:
        st.session_state.github_username = github_username_input

    st.divider()
    st.header("📄 Data Previews")

    # Toggle to show GitHub data
    if st.checkbox("Preview Fetched GitHub Projects", key="show_github_sidebar",help="Backend uses readme.md files of github repositories for appropriate analysis, so make sure you have given the access to the files in your access token"):
        current_gh_username = st.session_state.get("github_username")
        current_gh_token = st.session_state.get("github_pat")
        if current_gh_username:
            with st.spinner(f"Fetching GitHub data for '{current_gh_username}' preview..."):
                # Consider adding caching here if preview is used often
                @st.cache_data(ttl=600) # Cache for 10 minutes
                def cached_fetch_github_repos(username, token):
                    return fetch_github_repos(username, token)
                repos_preview = cached_fetch_github_repos(current_gh_username, current_gh_token)
                if not repos_preview:
                    repos_preview = fetch_github_repos(current_gh_username, current_gh_token)


            if isinstance(repos_preview, list) and repos_preview: # Check it's a non-empty list
                st.write(f"Found {len(repos_preview)} relevant repositories:")
                for repo_item in repos_preview[:5]: # Preview first 5
                    st.markdown(f"**{repo_item['name']}** - {repo_item.get('description', 'No description')}")
                    if repo_item.get('readme'):
                         st.caption(f"Readme snippet: {repo_item['readme'][:150]}...")
                    st.markdown("---")
            elif isinstance(repos_preview, list) and not repos_preview: # Empty list means no repos found
                 # Warning/info already shown by fetch_github_repos
                 pass
            # Error messages displayed by fetch_github_repos()
        else:
            st.warning("Enter a GitHub username first to preview projects.")


# --- Main area ---

# Section for Resume Upload
st.subheader("📄 Provide Your Resume")
st.markdown("You must upload your resume as a `.txt` file to use this tool.")

uploaded_file = st.file_uploader(
    "Upload Resume (.txt)",
    type=["txt"],
    key="resume_upload_widget" # Add a key for stability
)

# Immediately process uploaded file and store content in session state
if uploaded_file is not None:
    # Check if it's a new file upload or the same one from a previous run
    if uploaded_file.name != st.session_state.get("uploaded_resume_filename"):
        try:
            # Read content as bytes, then decode
            bytes_data = uploaded_file.getvalue()
            st.session_state.uploaded_resume_content = bytes_data.decode("utf-8")
            st.session_state.uploaded_resume_filename = uploaded_file.name
            st.success(f"Successfully uploaded and read '{uploaded_file.name}'.")
        except Exception as e:
            st.error(f"Error reading uploaded file '{uploaded_file.name}': {e}")
            # Clear potentially corrupted state
            st.session_state.uploaded_resume_content = None
            st.session_state.uploaded_resume_filename = None
    # If it's the same file name, we assume the content in session state is still valid
    # and don't need to re-read unless the widget state indicates a change.
    # This avoids re-reading on every interaction.
else:
    # If the uploader is cleared (shows no file), clear the session state too
    if st.session_state.get("uploaded_resume_filename") is not None:
        st.session_state.uploaded_resume_content = None
        st.session_state.uploaded_resume_filename = None

# with st.form("Asnwer on your behalf"):
#     st.subheader("Answer application questions with precision")
#     question_input = st.text_input("Question asked",
#                st.session_state.get("question", ""),                    
#             help="E.g., 'Where do you see yourself in next 2 years ?', 'Why we should hire you ?'")
#     ask_question_btn = st.form_submit_button("Answer on my Behalf")



def answer_with_gemini(github_data, resume_text, question,job_role,Company_name,job_description):
    """Sends data to Gemini API for analysis and returns the response text."""
    try:
        api_key = st.session_state.get("gemini_api_key")
        if not api_key:
            st.error("Gemini API key is missing. Please add it in the sidebar.")
            return "Error: Gemini API key is missing."

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash-latest', generation_config={"temperature": 0.1})

        prompt = f"""## Task: Provide answer to the question asked by the recruiter on behalf of job applicant based on resume, GitHub projects, and job description of the applicant.

        You are an AI assistant specialized in resume optimization and job application strategy. Analyze the provided resume content, GitHub project information (limited to name, description, and README), and job description to provide highly relevant and actionable advice.

        ### Resume Content:
        ```
        {resume_text}
        ```

        ### GitHub Projects (Name, Description, and README excerpts):

        {json.dumps(github_data, indent=2)}

        ### Job Role:
        {job_role}

        ### Company Name

        {Company_name}


        ### Job description

        {job_description}

        Question asked by the recruiter(Answer this question on candidate's behalf taking reference of his github and resume as knowledge base): 

        {question}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        st.error(f"Error analyzing with Gemini: {type(e).__name__} - {str(e)}")
        if "API key not valid" in str(e):
            st.error("Invalid Gemini API Key. Please check the key in the sidebar.")
        elif "quota" in str(e).lower():
             st.error("Quota exceeded for Gemini API. Check your usage limits or try again later.")
        elif "blocked" in str(e).lower():
             st.error("Content was blocked by the Gemini API safety filters. Please review inputs.")
        return f"An error occurred during Gemini analysis: {str(e)}"







# --- Form for job details ---
with st.form("job_details_form"):
    st.subheader("🎯 Job Details")
    col1, col2 = st.columns(2)
    with col1:
        job_role_input = st.text_input(
            "Job Position/Title",
            st.session_state.get("job_role", ""),
            help="E.g., 'Senior Python Developer', 'Machine Learning Engineer'"
        )
    with col2:
        company_name_input = st.text_input(
            "Company Name",
            st.session_state.get("company_name", ""),
            help="The company you're applying to"
        )
    job_description_input = st.text_area(
        "Paste Job Description Here",
        st.session_state.get("job_description", ""),
        height=250,
        help="Copy and paste the complete job description from the job posting"
    )
    submit_button = st.form_submit_button("🚀 Analyze Job Match")
    question_input = st.text_input("Question asked",
               st.session_state.get("question", ""),                    
            help="E.g., 'Where do you see yourself in next 2 years ?', 'Why we should hire you ?'")
    ask_question_btn = st.form_submit_button("Answer on my Behalf")


if ask_question_btn:
    st.session_state.question=question_input
    st.session_state.job_role = job_role_input
    st.session_state.company_name = company_name_input
    st.session_state.job_description = job_description_input
    valid_inputs = True
    if not st.session_state.get("question"):
        st.error("❗ Please enter your Question.")
        valid_inputs=False
    
    if not st.session_state.get("gemini_api_key"):
        st.error("❗ Please enter your Gemini API Key in the sidebar.")
        valid_inputs = False
    # Get resume content (only from uploaded file now)
    resume_text_main, resume_source = get_resume_content()
    if not resume_text_main and resume_source != "error":
        st.error("❗ No resume found. Please upload a 'resume.txt' file.")
        valid_inputs = False
    elif resume_source == "error":
        # Error message already shown by get_resume_content
        valid_inputs = False
    elif resume_source == "upload":
         st.info(f"✅ Using uploaded resume: '{st.session_state.uploaded_resume_filename}' for analysis.")
          # Job details validation
    if not job_role_input:
        st.error("❗ Please enter the Job Position/Title.")
        valid_inputs = False
    if not company_name_input:
        st.error("❗ Please enter the Company Name.")
        valid_inputs = False
    if not job_description_input:
        st.error("❗ Please enter a Job Description.")
        valid_inputs = False

    # Optional GitHub username validation (warning, not blocking)
    github_username_to_fetch = st.session_state.get("github_username")
    if not github_username_to_fetch:
        st.warning("⚠️ GitHub Username is not entered. Analysis will proceed without GitHub project data.")

   

    if valid_inputs:
        progress_bar_main = st.progress(0, text="⏳ Starting analysis...")
        status_text_main = st.empty()

        # Step 1: Fetch GitHub data (only if username provided)
        github_data_main = []
        if github_username_to_fetch:
            status_text_main.text(f"📡 Fetching GitHub repositories for '{github_username_to_fetch}'...")
            progress_bar_main.progress(25, text=f"📡 Fetching GitHub repositories...")
            # Pass the token from session state if available
            @st.cache_data(ttl=600) # Cache for 10 minutes
            def cached_fetch_github_repos(username, token):
                return fetch_github_repos(username, token)
            github_data_main = cached_fetch_github_repos(github_username_to_fetch,st.session_state.get("github_pat"))
            if not github_data_main:
                print("using non cached repo data")
                github_data_main = fetch_github_repos(
                    github_username_to_fetch,
                    st.session_state.get("github_pat")
                )
            # fetch_github_repos handles its own errors/warnings
        else:
             status_text_main.text("ℹ️ Skipping GitHub repository fetch (no username provided).")
             progress_bar_main.progress(25, text="ℹ️ Skipping GitHub repository fetch...")
             time.sleep(0.5) # Small delay

        # Step 2: Prepare data (Resume already loaded)
        status_text_main.text("⚙️ Preparing data for analysis...")
        progress_bar_main.progress(50, text="⚙️ Preparing data for analysis...")
        time.sleep(0.2)

        # Step 3: Call Gemini API
        status_text_main.text("🧠 Analyzing with Gemini AI...")
        progress_bar_main.progress(75, text="🧠 Analyzing with Gemini AI...")
        analysis_result_main = answer_with_gemini(
            github_data_main if isinstance(github_data_main, list) else [], # Ensure it's a list
            resume_text_main,
            question_input,
            job_role_input,
            company_name_input,
            job_description_input,
        )
        # Step 4: Display results
        status_text_main.text("✨ Analysis complete. Preparing results...")
        progress_bar_main.progress(100, text="✨ Analysis complete!")
        time.sleep(0.5)
        status_text_main.empty()
        progress_bar_main.empty()
        st.header(question_input)
        st.markdown(analysis_result_main)


    

# --- Process when form is submitted ---
if submit_button:
    # Persist form inputs
    st.session_state.job_role = job_role_input
    st.session_state.company_name = company_name_input
    st.session_state.job_description = job_description_input

    # Validation
    valid_inputs = True
    if not st.session_state.get("gemini_api_key"):
        st.error("❗ Please enter your Gemini API Key in the sidebar.")
        valid_inputs = False

    # Get resume content (only from uploaded file now)
    resume_text_main, resume_source = get_resume_content()
    if not resume_text_main and resume_source != "error":
        st.error("❗ No resume found. Please upload a 'resume.txt' file.")
        valid_inputs = False
    elif resume_source == "error":
        # Error message already shown by get_resume_content
        valid_inputs = False
    elif resume_source == "upload":
         st.info(f"✅ Using uploaded resume: '{st.session_state.uploaded_resume_filename}' for analysis.")

    # Optional GitHub username validation (warning, not blocking)
    github_username_to_fetch = st.session_state.get("github_username")
    if not github_username_to_fetch:
        st.warning("⚠️ GitHub Username is not entered. Analysis will proceed without GitHub project data.")

    # Job details validation
    if not job_role_input:
        st.error("❗ Please enter the Job Position/Title.")
        valid_inputs = False
    if not company_name_input:
        st.error("❗ Please enter the Company Name.")
        valid_inputs = False
    if not job_description_input:
        st.error("❗ Please enter a Job Description.")
        valid_inputs = False

    # Proceed if all essential inputs are valid
    if valid_inputs:
        progress_bar_main = st.progress(0, text="⏳ Starting analysis...")
        status_text_main = st.empty()

        # Step 1: Fetch GitHub data (only if username provided)
        github_data_main = []
        if github_username_to_fetch:
            status_text_main.text(f"📡 Fetching GitHub repositories for '{github_username_to_fetch}'...")
            progress_bar_main.progress(25, text=f"📡 Fetching GitHub repositories...")
            # Pass the token from session state if available
            @st.cache_data(ttl=600) # Cache for 10 minutes
            def cached_fetch_github_repos(username, token):
                return fetch_github_repos(username, token)
            github_data_main = cached_fetch_github_repos(github_username_to_fetch,st.session_state.get("github_pat"))
            if not github_data_main:
                print("using non cached repo data")
                github_data_main = fetch_github_repos(
                    github_username_to_fetch,
                    st.session_state.get("github_pat")
                )
            # fetch_github_repos handles its own errors/warnings
        else:
             status_text_main.text("ℹ️ Skipping GitHub repository fetch (no username provided).")
             progress_bar_main.progress(25, text="ℹ️ Skipping GitHub repository fetch...")
             time.sleep(0.5) # Small delay

        # Step 2: Prepare data (Resume already loaded)
        status_text_main.text("⚙️ Preparing data for analysis...")
        progress_bar_main.progress(50, text="⚙️ Preparing data for analysis...")
        time.sleep(0.2)

        # Step 3: Call Gemini API
        status_text_main.text("🧠 Analyzing with Gemini AI...")
        progress_bar_main.progress(75, text="🧠 Analyzing with Gemini AI...")
        analysis_result_main = analyze_with_gemini(
            github_data_main if isinstance(github_data_main, list) else [], # Ensure it's a list
            resume_text_main,
            job_description_input,
            job_role_input,
            company_name_input
        )

        # Step 4: Display results
        status_text_main.text("✨ Analysis complete. Preparing results...")
        progress_bar_main.progress(100, text="✨ Analysis complete!")
        time.sleep(0.5)
        status_text_main.empty()
        progress_bar_main.empty()

        display_results(analysis_result_main)
    else:
        st.warning("Analysis cannot proceed due to missing inputs or errors. Please check the messages above.")


# --- Footer ---
st.divider()
st.markdown("""
### 💡 How to Use This App:
1.  Enter your **Gemini API Key** in the sidebar.
2.  *(Optional)* Enter your **GitHub Username** and potentially a **GitHub Token** in the sidebar.
3.  **Upload** your resume (`.txt` format) using the uploader above.
4.  Fill in the **Job Details** and paste the **Job Description**.
5.  Click "**Analyze Job Match**" for tailored recommendations.
""")

st.markdown("<p style='text-align: center; margin-top:200px;'>© 2025 Ayushman Tomar</p>", unsafe_allow_html=True)