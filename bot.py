import discord
from discord.ext import commands
import os
import io
import aiohttp
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

TOKEN = os.environ.get("DISCORD_TOKEN")

REQUEST_CHANNEL_ID = 1520402264441884672
LOG_CHANNEL_ID = 1520405217210929162
REVIEW_CHANNEL_ID = 1520402893126111473
CATEGORY_ID = 1508218078058774555

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

pending_requests = {}
processed_messages = set()
image_store = {}


async def download_image(url: str) -> tuple[bytes, str]:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.read()
            content_type = resp.headers.get("Content-Type", "image/png")
            ext = content_type.split("/")[-1].split(";")[0]
            if ext not in ["png", "jpg", "jpeg", "gif", "webp"]:
                ext = "png"
            return data, ext


def add_watermark(img_bytes: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        draw = ImageDraw.Draw(img)

        text = "© Depth Of School"
        font_size = max(20, img.width // 20)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except Exception:
            try:
                font = ImageFont.truetype("/nix/store/1bkxf69hxs39mi6l5bxs89ym1qpyjzq-dejavu-fonts-2.37/share/fonts/truetype/DejaVuSans-Bold.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        margin = 15
        x = img.width - text_w - margin
        y = img.height - text_h - margin

        # ظل للنص
        draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 180))
        # النص الأبيض
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 230))

        output = io.BytesIO()
        img = img.convert("RGB")
        img.save(output, format="JPEG", quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"⚠️ فشل الواترمارك: {e}")
        return img_bytes


class ReviewView(discord.ui.View):
    def __init__(self, user_id, room_name, extra_text=""):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.room_name = room_name
        self.extra_text = extra_text

    @discord.ui.button(label="✅ قبول", style=discord.ButtonStyle.success, custom_id="accept_btn")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        print(f"🔘 زر القبول - user_id={self.user_id} room={self.room_name}")
        await interaction.response.defer()

        guild = interaction.guild
        new_channel = None

        try:
            channel_name = self.room_name.replace(" ", "-") if self.room_name else "روم-جديد"
            category = guild.get_channel(CATEGORY_ID)
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True, send_messages=True,
                    embed_links=True, attach_files=True, read_message_history=True
                )
            }
            new_channel = await guild.create_text_channel(
                name=channel_name, category=category,
                overwrites=overwrites, reason="طلب مقبول"
            )
            print(f"✅ تم إنشاء القناة: {new_channel.name}")
        except Exception as e:
            print(f"❌ فشل إنشاء القناة: {e}")

        if new_channel:
            try:
                img_bytes = image_store.get(self.user_id)
                if img_bytes and len(img_bytes) > 0:
                    print(f"📸 إرسال الصورة ({len(img_bytes)} bytes)")
                    file = discord.File(io.BytesIO(img_bytes), filename="image.jpg")
                    embed_channel = discord.Embed(color=discord.Color.gold(), timestamp=datetime.utcnow())
                    if self.extra_text:
                        embed_channel.description = self.extra_text
                    embed_channel.set_image(url="attachment://image.jpg")
                    embed_channel.set_footer(text="© Depth Of School")
                    await new_channel.send(file=file, embed=embed_channel)
                    print(f"✅ تم إرسال الصورة في الروم")
                    del image_store[self.user_id]
                else:
                    print(f"⚠️ الصورة غير موجودة")
            except Exception as e:
                print(f"❌ فشل إرسال الصورة: {e}")

        user = bot.get_user(self.user_id)
        if user:
            try:
                msg = "✅ **تم قبول طلبك!**\n\nتم إنشاء الروم الخاص بك في السيرفر."
                if new_channel:
                    msg += f"\n\n📌 الروم: {new_channel.mention}"
                await user.send(msg)
            except Exception as e:
                print(f"⚠️ فشل DM: {e}")

        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            embed = discord.Embed(title="✅ طلب مقبول", color=discord.Color.green(), timestamp=datetime.utcnow())
            embed.add_field(name="المراجع", value=interaction.user.mention, inline=True)
            embed.add_field(name="الروم", value=self.room_name, inline=True)
            if new_channel:
                embed.add_field(name="القناة المنشأة", value=new_channel.mention, inline=True)
            await log_channel.send(embed=embed)
        except Exception as e:
            print(f"❌ فشل اللوق: {e}")

        try:
            await interaction.message.edit(content=f"✅ **تم القبول** بواسطة {interaction.user.mention}", view=None)
        except Exception as e:
            print(f"⚠️ {e}")

        pending_requests.pop(self.user_id, None)
        print("✅ انتهى معالجة القبول")

    @discord.ui.button(label="❌ رفض", style=discord.ButtonStyle.danger, custom_id="reject_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RejectModal(self.user_id, self.room_name, interaction.message))


class RejectModal(discord.ui.Modal, title="سبب الرفض"):
    reason = discord.ui.TextInput(
        label="أدخل سبب الرفض",
        placeholder="مثال: الصورة غير واضحة...",
        required=True, max_length=500
    )

    def __init__(self, user_id, room_name, review_message):
        super().__init__()
        self.user_id = user_id
        self.room_name = room_name
        self.review_message = review_message

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user = bot.get_user(self.user_id)
        if user:
            try:
                await user.send(f"❌ **تم رفض طلبك**\n\n**السبب:** {self.reason.value}")
            except Exception:
                pass

        try:
            log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
            embed = discord.Embed(title="❌ طلب مرفوض", color=discord.Color.red(), timestamp=datetime.utcnow())
            embed.add_field(name="المراجع", value=interaction.user.mention, inline=True)
            embed.add_field(name="الروم", value=self.room_name, inline=True)
            embed.add_field(name="السبب", value=self.reason.value, inline=False)
            await log_channel.send(embed=embed)
        except Exception as e:
            print(f"❌ فشل اللوق: {e}")

        try:
            await self.review_message.edit(
                content=f"❌ **تم الرفض** بواسطة {interaction.user.mention} | السبب: {self.reason.value}",
                view=None
            )
        except Exception:
            pass

        pending_requests.pop(self.user_id, None)
        image_store.pop(self.user_id, None)


@bot.event
async def on_ready():
    print(f"✅ البوت شغال: {bot.user.name}")
    print(f"ID: {bot.user.id}")


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id == REQUEST_CHANNEL_ID:
        if message.id in processed_messages:
            return
        processed_messages.add(message.id)

        lines = message.content.strip().splitlines()
        room_name = lines[0].strip() if lines else "غير محدد"
        extra_text = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if message.attachments:
            for attachment in message.attachments:
                if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                    print(f"📸 صورة جديدة من {message.author} - الروم: {room_name}")

                    user_id = message.author.id

                    if user_id in pending_requests:
                        try:
                            await message.delete()
                        except Exception:
                            pass
                        try:
                            await message.author.send("⚠️ لديك طلب قيد المراجعة بالفعل. انتظر حتى يتم البت فيه.")
                        except Exception:
                            pass
                        return

                    # تحميل الصورة قبل الحذف
                    img_bytes = None
                    try:
                        print(f"⬇️ تحميل الصورة...")
                        raw_bytes, ext = await download_image(attachment.url)
                        print(f"✅ تم التحميل ({len(raw_bytes)} bytes) — إضافة الواترمارك...")
                        img_bytes = add_watermark(raw_bytes)
                        image_store[user_id] = img_bytes
                        print(f"✅ الصورة جاهزة مع الواترمارك ({len(img_bytes)} bytes)")
                    except Exception as e:
                        print(f"⚠️ فشل تحميل/واترمارك: {e}")

                    # حذف الرسالة
                    try:
                        await message.delete()
                    except Exception:
                        pass

                    # إرسال الطلب لقناة المراجعة مع الصورة مباشرة
                    try:
                        review_channel = await bot.fetch_channel(REVIEW_CHANNEL_ID)

                        embed = discord.Embed(
                            title="📋 طلب جديد للمراجعة",
                            color=discord.Color.blue(),
                            timestamp=datetime.utcnow()
                        )
                        embed.add_field(name="اسم الروم", value=room_name, inline=False)
                        if extra_text:
                            embed.add_field(name="الكلام", value=extra_text, inline=False)
                        embed.set_footer(text="© Depth Of School")

                        view = ReviewView(user_id, room_name, extra_text)

                        if img_bytes and len(img_bytes) > 0:
                            embed.set_image(url="attachment://preview.jpg")
                            file = discord.File(io.BytesIO(img_bytes), filename="preview.jpg")
                            review_msg = await review_channel.send(file=file, embed=embed, view=view)
                        else:
                            embed.set_image(url=attachment.url)
                            review_msg = await review_channel.send(embed=embed, view=view)

                        pending_requests[user_id] = review_msg.id
                        print(f"✅ تم إرسال الطلب مع الصورة لقناة المراجعة")

                    except Exception as e:
                        print(f"❌ خطأ في قناة المراجعة: {e}")

                    try:
                        log_channel = await bot.fetch_channel(LOG_CHANNEL_ID)
                        log_embed = discord.Embed(title="📥 طلب جديد", color=discord.Color.blue(), timestamp=datetime.utcnow())
                        log_embed.add_field(name="الروم", value=room_name, inline=True)
                        log_embed.add_field(name="الحالة", value="⏳ قيد المراجعة", inline=True)
                        await log_channel.send(embed=log_embed)
                    except Exception as e:
                        print(f"⚠️ فشل اللوق: {e}")

                    try:
                        await message.author.send("✅ **تم استلام طلبك!**\n\nصورتك قيد المراجعة من قبل الإدارة. ستصلك رسالة خاصة عند البت في طلبك.")
                    except Exception:
                        pass

                    return

        try:
            await message.delete()
        except Exception:
            pass
        try:
            await message.author.send("⚠️ **يجب إرسال صورة فقط في هذه القناة.**\n\nأرسل صورتك مع كتابة اسم الروم في نفس الرسالة.")
        except Exception:
            pass

    await bot.process_commands(message)


@bot.command(name="pending")
@commands.has_permissions(administrator=True)
async def pending_cmd(ctx):
    if not pending_requests:
        await ctx.send("✅ لا توجد طلبات معلقة حالياً.")
        return
    embed = discord.Embed(title="⏳ الطلبات المعلقة", color=discord.Color.orange(), timestamp=datetime.utcnow())
    for user_id, msg_id in pending_requests.items():
        embed.add_field(name=f"<@{user_id}>", value=f"ID: {msg_id}", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="cancel")
@commands.has_permissions(administrator=True)
async def cancel_cmd(ctx, user_id: int):
    if user_id in pending_requests:
        pending_requests.pop(user_id, None)
        image_store.pop(user_id, None)
        await ctx.send(f"✅ تم إلغاء طلب <@{user_id}>.")
        user = bot.get_user(user_id)
        if user:
            try:
                await user.send("❌ تم إلغاء طلبك من قبل الإدارة.")
            except Exception:
                pass
    else:
        await ctx.send(f"⚠️ لا يوجد طلب معلق للعضو <@{user_id}>.")


bot.run(TOKEN)
