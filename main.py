import re

# DISCORD INCLUDES
import nextcord
from nextcord import Interaction, SlashOption
from nextcord.ext import commands
import discord

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

# Level of access to drive (for writing to a file)
SCOPES = ['https://www.googleapis.com/auth/drive']

# Role used for chat requests
role = ("Ufoh is a chatbot that applies a numeric grading to an input target message that optionally has up to five "
        "context messages (messages directly prior to the target) and a message being specifically replied to. "
        "True/false variables for hate against race, religion, origin, gender, sexuality, age, and disabilities are "
        "also provided in the output. Supportive range: -5 < 0, Neutral: 0, Hateful range: 0 < 5. The target message is "
        "specified by starting with 'Message To Evaluate', while the messages previously said by OTHER PEOPLE is under "
        "CONTEXT ---, where 'Message Being Replied To' is a directly reply. However, note that just because there is "
        "not a specific message being replied to doesn't mean that the previous messages are not indirectly being "
        "replied to. Therefore, take the context of the previous messages into account as well. Format the output in "
        "this way: hate_speech_score: #, target_race: true/false, target_religion: true/false, target_origin: true/false, "
        "target_gender: true/false, target_sexuality: true/false, target_age: true/false, target_disability: true/false. "
        "Example input: CONTEXT --- Message n-5: Hey guys Message n-4: Welcome Message n-3: Hii Message n-2: Welcome in "
        "bro Message n-1: Yessir Message Being Replied To: N/A TARGET --- Message To Evaluate: Shut up! Example output: "
        "hate_speech_score: 1 target_race: False target_religion: False target_origin: False target_gender: False "
        "target_sexuality: False target_age: False target_disability: False. Note that hate_speech_score is POSITIVE "
        "because the more POSITIVE the score, the MORE hateful the message.")

# Login for Google Drive (needs access to a cloud file)
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
    # Locate file
    results = service.files().list(q=f"name='{file_name}'", fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        print('File not found.')
        return

    file_id = items[0]['id']

    # Get file contents
    request = service.files().get_media(fileId=file_id)
    existing_content = request.execute()

    # Assuming the file content is in a plain text format and can be decoded
    try:
        existing_content = existing_content.decode('utf-8')
    except AttributeError:
        existing_content = ''

    # For appending to the file
    new_content = existing_content + '\n' + content_to_append

    # Convert the new combined string to bytes and make a file-like object
    fh = BytesIO(new_content.encode())
    media = MediaIoBaseUpload(fh, mimetype='text/plain', resumable=True)
    # Update the file with the new content
    service.files().update(fileId=file_id, media_body=media).execute()

# Function to determine if the output matches the desired format
def is_correct_format(output):
    required_fields = [
        "hate_speech_score", "target_race", "target_religion",
        "target_origin", "target_gender", "target_sexuality",
        "target_age", "target_disability"
    ]
    for field in required_fields:
        if f"{field}:" not in output:
            return False
    return True

def convert_value(value):
    # Remove any trailing non-numeric characters (like the trailing period in "False.")
    value = re.sub(r'\W+$', '', value)
    # Convert to appropriate data type
    if value.isdigit() or re.match(r'^-?\d+\.?\d*$', value):
        return float(value)  # Handle integers and floats
    elif value in ['True', 'False']:
        return value == 'True'
    return value

# Fine-tuning buttons
class AdjustScoreView(discord.ui.View):
    def __init__(self, author, content, score, race, religion, origin, gender, sexuality, age, disability, msgn1, msgn2, msgn3, msgn4, msgn5, msgr):
        super().__init__()
        self.author = author
        self.content = content
        self.msgn1 = msgn1
        self.msgn2 = msgn2
        self.msgn3 = msgn3
        self.msgn4 = msgn4
        self.msgn5 = msgn5
        self.msgr = msgr
        self.score = score
        self.race = race
        self.religion = religion
        self.origin = origin
        self.gender = gender
        self.sexuality = sexuality
        self.age = age
        self.disability = disability

    # Submit jsonl formatted user corrected output for fine-tuning
    @discord.ui.button(label="Submit for Fine-tuning", style=discord.ButtonStyle.primary)
    async def submit(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return

        # Respond to the interaction first
        await interaction.response.send_message("Your feedback has been provided successfully.", ephemeral=True)

        input = "CONTEXT --- Message n-5: " + self.msgn5 + " Message n-4: " + self.msgn4 + " Message n-3: " + self.msgn3 + " Message n-2: " + self.msgn2 + " Message n-1: " + self.msgn1 + " Message Being Replied To: " + self.msgr + " TARGET --- Message To Evaluate: " + self.content
        output = f"hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}"
        jsonl = "{\"messages\": [{\"role\": \"system\", \"content\": \"" + role + ".\"}, {\"role\": \"user\", \"content\": \"" + input + "\"}, {\"role\": \"assistant\", \"content\": \"" + output + "\"}]}"
        write_to_file(service, file_name, jsonl)

        # Disable all buttons in this view
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        # Update the message (not the initial response)
        await interaction.followup.edit_message(interaction.message.id, view=self)

    # Buttons for user correction (increase/decrease hate score or toggle each category true/false)
    @discord.ui.button(label="Increase Score", style=discord.ButtonStyle.green)
    async def increase_score(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.score += 1  # 
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")

    @discord.ui.button(label="Decrease Score", style=discord.ButtonStyle.red)
    async def decrease_score(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.score -= 1  
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")
        
    @discord.ui.button(label="Toggle target_race", style=discord.ButtonStyle.secondary)
    async def toggle_race(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.race = not self.race
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")
    
    @discord.ui.button(label="Toggle target_religion", style=discord.ButtonStyle.secondary)
    async def toggle_religion(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.religion = not self.religion
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")
    
    @discord.ui.button(label="Toggle target_origin", style=discord.ButtonStyle.secondary)
    async def toggle_origin(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.origin = not self.origin
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")
    
    @discord.ui.button(label="Toggle target_gender", style=discord.ButtonStyle.secondary)
    async def toggle_gender(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.gender = not self.gender
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")

    @discord.ui.button(label="Toggle target_sexuality", style=discord.ButtonStyle.secondary)
    async def toggle_sexuality(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.sexuality = not self.sexuality
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")

    @discord.ui.button(label="Toggle target_age", style=discord.ButtonStyle.secondary)
    async def toggle_age(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.age = not self.age
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")

    @discord.ui.button(label="Toggle target_disability", style=discord.ButtonStyle.secondary)
    async def toggle_disability(self, button: discord.ui.Button, interaction: discord.Interaction):
        if interaction.user != self.author:
            await interaction.response.send_message("You are not authorized to change this score.", ephemeral=True)
            return
        self.disability = not self.disability
        await interaction.message.edit(content=f"\nCorrected Model Output: hate_speech_score: {self.score} target_race: {self.race} target_religion: {self.religion} target_origin: {self.origin} target_gender: {self.gender} target_sexuality: {self.sexuality} target_age: {self.age} target_disability: {self.disability}")

# Initialize OpenAI API
os.environ["OPENAI_API_KEY"] = userdata.get('openapikey')
client = OpenAI()

# GDrive API
service = service_account_login()
file_name = 'ufohFT.txt'  # Update with filename to store jsonl formatted user-corrected outputs

intents = nextcord.Intents.default()
intents = nextcord.Intents().all()
bot = commands.Bot(command_prefix="!", intents=intents)

# User input thresholds, if the score is above the threshold for a specific one, do something to the user. Priority: ban > kick > warn
# Dictionary to hold thresholds
thresholds = {
    'banhsth': 2, 'banraceth': 2, 'banreligionth': 2, 'banoriginth': 2,
    'bangenderth': 2, 'bansexth': 2, 'banageth': 2, 'bandisth': 2,
    'kickhsth': 1, 'kickraceth': 1, 'kickreligionth': 1, 'kickoriginth': 1,
    'kickgenderth': 1, 'kicksexth': 1, 'kickageth': 1, 'kickdisth': 1,
    'warnhsth': 0, 'warnraceth': 0, 'warnreligionth': 0, 'warnoriginth': 0,
    'warngenderth': 0, 'warnsexth': 0, 'warnageth': 0, 'warndisth': 0
}

@bot.event
async def on_ready():
    print(f"{bot.user.name} is ready!")

# Enable/disable logs
logging = True
logschannel = userdata.get('logschannel')

# Allow administrators to configure specific moderation thresholds (what severity of hate speech determines what action)
@bot.slash_command(description="Set specific moderation thresholds (default: ban = 3, kick = 2, warn = 1)")
async def setth(
    interaction: Interaction,
    threshold_type: str = SlashOption(
        name="type",
        description="The type of threshold to set",
        choices=[
            "banhsth", "banraceth", "banreligionth", "banoriginth",
            "bangenderth", "bansexth", "banageth", "bandisth",
            "kickhsth", "kickraceth", "kickreligionth", "kickoriginth",
            "kickgenderth", "kicksexth", "kickageth", "kickdisth",
            "warnhsth", "warnraceth", "warnreligionth", "warnoriginth",
            "warngenderth", "warnsexth", "warnageth", "warndisth"
        ]
    ),
    value: int = SlashOption(
        name="value",
        description="The new threshold value",
        required=True
    )
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You are not authorized to run this command.", ephemeral=True)
    else:
        # Set the new threshold
        if threshold_type in thresholds:
            thresholds[threshold_type] = value
            await interaction.response.send_message(f"Threshold {threshold_type} has been set to {value}.")
        else:
            await interaction.response.send_message("Invalid threshold type.", ephemeral=True)

# Allow administrators to configure general moderation thresholds (what severity of hate speech determines what action)
@bot.slash_command(description="Set general moderation thresholds (default: ban = 3, kick = 2, warn = 1)")
async def setallth(
    interaction: Interaction,
    threshold_type: str = SlashOption(
        name="type",
        description="The type of threshold to set",
        choices=[
            "ban", "kick", "warn"
        ]
    ),
    value: int = SlashOption(
        name="value",
        description="The new threshold value",
        required=True
    )
):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("You are not authorized to run this command.", ephemeral=True)
    else:
        if threshold_type in ['ban', 'kick', 'warn']:
            # Update all matching thresholds for the generalized type
            updated = False
            for key in list(thresholds.keys()):
                if key.startswith(threshold_type):
                    thresholds[key] = value
                    updated = True
            if updated:
                await interaction.response.send_message(f"All {threshold_type} thresholds have been set to {value}.")
            else:
                await interaction.response.send_message(f"No thresholds updated for {threshold_type}.", ephemeral=True)
        else:
            await interaction.response.send_message("Invalid threshold type.", ephemeral=True)

@bot.event
async def on_message(target):
    # Ignore messages from the bot itself
    if target.author == bot.user:
        return
    
    # Variable to hold the content of the replied-to message, if it exists
    msgr = "N/A"

    # Check if the current message is a reply to another message
    if target.reference and target.reference.resolved:
        # If the reference is resolved, access the content directly
        msgr = target.reference.resolved.content
    elif target.reference:
        # If the reference exists but is not resolved, fetch the message
        try:
            original_msg = await target.channel.fetch_message(target.reference.message_id)
            msgr = original_msg.content
        except Exception as e:
            msgr = "N/A"

    if msgr == "":
        msgr == "N/A"
    
    # Check and fetch the last five messages before the current one
    history = await target.channel.history(limit=5, before=target).flatten()
    # This will store messages with messages[0] being the most recent one before the target message

    # Assign each message to a variable if they exist
    msgn1 = history[0].content if len(history) > 0 else "N/A"
    msgn2 = history[1].content if len(history) > 1 else "N/A"
    msgn3 = history[2].content if len(history) > 2 else "N/A"
    msgn4 = history[3].content if len(history) > 3 else "N/A"
    msgn5 = history[4].content if len(history) > 4 else "N/A"

    input = "CONTEXT --- Message n-5:" + msgn5 + "Message n-4:" + msgn4 + "Message n-3:" + msgn3 + "Message n-2:" + msgn2 + "Message n-1:" + msgn1 + "Message Being Replied To:" + msgr + "TARGET --- Message To Evaluate: " + target.content

    # Call the OpenAI API to analyze the message
    completion = client.chat.completions.create(
    model="ft:gpt-3.5-turbo-0125:personal:ufoh-v3:9ETnxurq",
    messages=[
        {"role": "system", "content": role},
        {"role": "user", "content": input}
        ]
    )
    
    # MODERATION POLICY
    ai_output = str(completion.choices[0].message)

    # Try to find a valid output format (5 times max)
    valid_output_found = is_correct_format(ai_output)
    index = 0
    while not valid_output_found and index < min(5, len(completion.choices)):
        ai_output = str(completion.choices[index].message)
        valid_output_found = is_correct_format(ai_output)
        index += 1

    # If no valid output is found, send error and terminate
    if not valid_output_found:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"Model failed to parse message (no valid output).")
        return
    
    # Extract the content part of the string
    try:
        # Attempt to parse the content string from ai_output
        content_str = ai_output.split("content='")[1].split("', role=")[0]
    except IndexError:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"Model failed to parse message (content extraction failed)")
        return
    
    # Assign each parsed keyword to its value
    # Using the updated regex to extract key-value pairs
    matches = re.finditer(r'(\w+):\s*([-\w.]+)', content_str)
    parsed_data = {match.group(1): match.group(2) for match in matches}

    # Apply conversion to each item in the dictionary
    converted_data = {k: convert_value(v) for k, v in parsed_data.items()}
    
    # Initialize values
    ai_hate_speech_score = converted_data['hate_speech_score']
    ai_target_race = converted_data['target_race']
    ai_target_religion = converted_data['target_religion']
    ai_target_origin = converted_data['target_origin']
    ai_target_gender = converted_data['target_gender']
    ai_target_sexuality = converted_data['target_sexuality']
    ai_target_age = converted_data['target_age']
    ai_target_disability = converted_data['target_disability']
    
    # Ban/kick/warn actions disabled for testing purposes
    if ai_hate_speech_score <= 0:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\nNo action was taken (hate_speech_score <= 0).")
        return
    if ai_hate_speech_score > thresholds['banraceth'] and ai_target_race == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the target_race threshold ({thresholds['banraceth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="Racism")
    elif ai_hate_speech_score > thresholds['banreligionth'] and ai_target_religion == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the target_religion threshold ({thresholds['banreligionth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="Religious discrimination")
    elif ai_hate_speech_score > thresholds['banoriginth'] and ai_target_origin == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the target_origin threshold ({thresholds['banoriginth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="Ethnicity discrimination")
    elif ai_hate_speech_score > thresholds['bangenderth'] and ai_target_gender == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the target_gender threshold ({thresholds['bangenderth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="Sexism")
    elif ai_hate_speech_score > thresholds['bansexth'] and ai_target_sexuality == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the target_sexuality threshold ({thresholds['bansexth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="Homophobia/Transphobia")
    elif ai_hate_speech_score > thresholds['banageth'] and ai_target_age == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the target_age threshold ({thresholds['banageth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="Ageism")
    elif ai_hate_speech_score > thresholds['bandisth'] and ai_target_disability == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the target_disability threshold ({thresholds['bandisth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="Ableism")
    elif ai_hate_speech_score > thresholds['banhsth']:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was banned as the general hate speech threshold ({thresholds['banhsth']}) for bans was exceeded ({ai_hate_speech_score})")
        #await message.author.ban(reason="General hate speech")
    elif ai_hate_speech_score > thresholds['kickraceth'] and ai_target_race == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the target_race threshold ({thresholds['kickraceth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="Racism")
    elif ai_hate_speech_score > thresholds['kickreligionth'] and ai_target_religion == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the target_religion threshold ({thresholds['kickreligionth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="Religious discrimination")
    elif ai_hate_speech_score > thresholds['kickoriginth'] and ai_target_origin == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the target_origin threshold ({thresholds['kickoriginth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="Ethnicity discrimination")
    elif ai_hate_speech_score > thresholds['kickgenderth'] and ai_target_gender == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the target_gender threshold ({thresholds['kickgenderth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="Sexism")
    elif ai_hate_speech_score > thresholds['kicksexth'] and ai_target_sexuality == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the target_sexuality threshold ({thresholds['kicksexth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="Homophobia/Transphobia")
    elif ai_hate_speech_score > thresholds['kickageth'] and ai_target_age == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the target_age threshold ({thresholds['kickageth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="Ageism")
    elif ai_hate_speech_score > thresholds['kickdisth'] and ai_target_disability == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the target_disability threshold ({thresholds['kickdisth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="Ableism")
    elif ai_hate_speech_score > thresholds['kickhsth']:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was kicked as the general hate speech threshold ({thresholds['kickhsth']}) for kicks was exceeded ({ai_hate_speech_score})")
        #await message.author.kick(reason="General hate speech")
    elif ai_hate_speech_score > thresholds['warnraceth'] and ai_target_race == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the target_race threshold ({thresholds['warnraceth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="Racism")
    elif ai_hate_speech_score > thresholds['warnreligionth'] and ai_target_religion == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the target_religion threshold ({thresholds['warnreligionth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="Religious discrimination")
    elif ai_hate_speech_score > thresholds['warnoriginth'] and ai_target_origin == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the target_origin threshold ({thresholds['warnoriginth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="Ethnicity discrimination")
    elif ai_hate_speech_score > thresholds['warngenderth'] and ai_target_gender == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the target_gender threshold ({thresholds['warngenderth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="Sexism")
    elif ai_hate_speech_score > thresholds['warnsexth'] and ai_target_sexuality == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the target_sexuality threshold ({thresholds['warnsexth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="Homophobia/Transphobia")
    elif ai_hate_speech_score > thresholds['warnageth'] and ai_target_age == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the target_age threshold ({thresholds['warnageth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="Ageism")
    elif ai_hate_speech_score > thresholds['warndisth'] and ai_target_disability == True:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the target_disability threshold ({thresholds['warndisth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="Ableism")
    elif ai_hate_speech_score > thresholds['warnhsth']:
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\n{target.author.mention} was warned as the general hate speech threshold ({thresholds['warnhsth']}) for warns was exceeded ({ai_hate_speech_score})")
        #await message.author.warn(reason="General hate speech")
    else: # debug
        log_channel = bot.get_channel(logschannel)
        await log_channel.send(f"User: {target.author.mention}\n\nMessage: {target.content}\n\nModel Output: {content_str}\n\nNo action was taken. (Hate speech score less than lowest threshold)")

    # TAKE USER CORRECTION
    view = AdjustScoreView(target.author, target.content, ai_hate_speech_score, ai_target_race, ai_target_religion, ai_target_origin, ai_target_gender, ai_target_sexuality, ai_target_age, ai_target_disability, msgn1, msgn2, msgn3, msgn4, msgn5, msgr)
    await log_channel.send(f"Fine-tuning Options", view=view)

    await bot.process_commands(target)  # To allow other bot commands to work

bot.run(userdata.get('botkey'))
