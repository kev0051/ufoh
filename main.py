# conda env: ufoh

# DISCORD INCLUDES
import nextcord
from nextcord import Interaction, SlashOption
from nextcord.ext import commands

# GDRIVE INCLUDES (FOR WRITING TO A FILE)
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaIoBaseUpload
from io import BytesIO
import os.path

# GPT CALL INCLUDES
import openai
from openai import OpenAI

# Scopes define the level of access you need
SCOPES = ['https://www.googleapis.com/auth/drive']

def service_account_login():
    """Log in to Google API and return service object."""
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('drive', 'v3', credentials=creds)

def read_file(service, file_name):
    """Read file content from Google Drive."""
    results = service.files().list(q=f"name='{file_name}'", fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        print('No files found.')
        return None
    else:
        file_id = items[0]['id']
        request = service.files().get_media(fileId=file_id)
        file = request.execute()
        print(file)

def write_to_file(service, file_name, content_to_append):
    """Append content to a file in Google Drive on a new line."""
    # Step 1: Find the file by name and get its ID.
    results = service.files().list(q=f"name='{file_name}'", fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        print('File not found.')
        return

    file_id = items[0]['id']

    # Step 2: Download the existing content of the file.
    request = service.files().get_media(fileId=file_id)
    existing_content = request.execute()

    # Assuming the file content is in a plain text format and can be decoded.
    try:
        existing_content = existing_content.decode('utf-8')
    except AttributeError:
        existing_content = ''

    # Step 3: Append new content to the existing content.
    new_content = existing_content + '\n' + content_to_append

    # Step 4: Upload the new content back to Google Drive.
    # Convert the new combined string to bytes and make a file-like object.
    fh = BytesIO(new_content.encode())
    media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=True)
    # Update the file with the new content.
    service.files().update(fileId=file_id, media_body=media).execute()

# Initialize OpenAI API
os.environ["OPENAI_API_KEY"] = [put your OpenAI key here]
client = OpenAI()

intents = nextcord.Intents.default()
intents = nextcord.Intents().all()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"{bot.user.name} is ready!")

@bot.slash_command()
async def test(interaction: nextcord.Integration, user: nextcord.Member):
    await interaction.response.send_message(f"{user.mention}")

logging = True
logschannel = [put your logs channel id here]

role = "You are a chatbot that determines if a message being sent is harmful. Depending on the verdict you make, your response will be as follows, only selecting one of the four options: VERDICT - warn/kick/ban/none"

@bot.slash_command()
async def test2(interaction: nextcord.Interaction, user: nextcord.Member, reason: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You are not authorized to run this command.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Kicked {user.mention}", ephemeral=True)
        if logging is True:
            log_channel = bot.get_channel(logschannel)
            await log_channel.send(f"{user.mention} was kicked by {interaction.user.mention} for {reason}")
        #await user.kick(reason=reason)

@bot.event
async def on_message(target):
    # Ignore messages from the bot itself
    if target.author == bot.user:
        return

    # Call the OpenAI API to analyze the message
    completion = client.chat.completions.create(
    model="gpt-4-turbo",
    messages=[
        {"role": "system", "content": role},
        {"role": "user", "content": "Review this message for harmful content: " + target.content}
        ]
    )
    
    # Example of moderation logic
    content = str(completion.choices[0].message).strip().lower()
    if "warn" in content:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"{target.author.mention} was warned, determined by the model.")
    elif "kick" in content:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"{target.author.mention} was kicked, determined by the model.")
        #await message.author.kick(reason="Violating guidelines")
    elif "ban" in content:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"{target.author.mention} was banned, determined by the model.")
        #await message.author.ban(reason="Severe violation of guidelines")
    elif "none" in content:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"{target.author.mention} - good job, you are doing good.")
    
    await bot.process_commands(target)  # To allow other bot commands to work

service = service_account_login()
file_name = 'test.txt'  # Update with your file's name
#read_file(service, file_name)
#write_to_file(service, file_name, 'Hello, world! New content appended yuh!')

bot.run([bot key here])
