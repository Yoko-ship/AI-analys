"""Compose the website's account services; persistence belongs to identity modules."""
from identity.database import IdentityDatabase
from identity.users import WebUser, is_admin_email
from identity.sessions import Sessions
from identity.accounts import Accounts
from identity.oauth import Oauth
from identity.security import Security
from identity.profile import Profile
from identity.favorites import Favorites
from identity.research import Research
from identity.notes import Notes
from identity.support import Support
from identity.portfolio import Portfolio
from identity.notifications import Notifications


class WebAuthStore:
    def __init__(self, database_url=None):
        self.database = IdentityDatabase(database_url)
        self.sessions = Sessions(self.database)
        self.oauth = Oauth(self.database, self.sessions)
        self.accounts = Accounts(self.database, self.oauth, self.sessions)
        self.security = Security(self.database)
        self.favorites = Favorites(self.database)
        self.research = Research(self.database)
        self.notes = Notes(self.database)
        self.profile = Profile(self.database, self.notes, self.sessions)
        self.support = Support(self.database)
        self.portfolio = Portfolio(self.database)
        self.notifications = Notifications(self.database)


web_auth_store = WebAuthStore()
