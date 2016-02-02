__author__ = 'chris'

import os
import sqlite3 as lite
from collections import Counter
from config import DATA_FOLDER
from dht.node import Node
from dht.utils import digest
from protos import objects
from protos.objects import Listings, Followers, Following
from os.path import join


class Database(object):

    # pylint: disable=W0601
    DATABASE = None

    def __init__(self, testnet=False, filepath=None):
        global DATABASE

        DATABASE = _database_path(testnet, filepath)
        _initialize_datafolder_tree()
        _initialize_database(DATABASE)

    @staticmethod
    def get_database_path():
        return DATABASE

    class HashMap(object):
        """
        Creates a table in the database for mapping file hashes (which are sent
        over the wire in a query) with a more human readable filename in local
        storage. This is useful for users who want to look through their store
        data on disk.
        """

        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def insert(self, hash_value, filepath):
            cursor = self.db.cursor()
            cursor.execute('''INSERT OR REPLACE INTO hashmap(hash, filepath)
                          VALUES (?,?)''', (hash_value, filepath))
            self.db.commit()

        def get_file(self, hash_value):
            cursor = self.db.cursor()
            cursor.execute('''SELECT filepath FROM hashmap WHERE hash=?''', (hash_value,))
            ret = cursor.fetchone()
            if ret is None:
                return None
            return ret[0]

        def get_all(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT * FROM hashmap ''')
            ret = cursor.fetchall()
            return ret

        def delete(self, hash_value):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM hashmap WHERE hash = ?''', (hash_value,))
            self.db.commit()

        def delete_all(self):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM hashmap''')
            self.db.commit()

    class ProfileStore(object):
        """
        Stores the user's profile data in the db. The profile is stored as a serialized
        Profile protobuf object. It's done this way because because protobuf is more
        flexible and allows for storing custom repeated fields (like the SocialAccount
        object). Also we will just serve this over the wire so we don't have to manually
        rebuild it every startup. To interact with the profile you should use the
        `market.profile` module and not this class directly.
        """

        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def set_proto(self, proto):
            cursor = self.db.cursor()
            handle = self.get_temp_handle()
            cursor.execute('''INSERT OR REPLACE INTO profile(id, serializedUserInfo, tempHandle)
                          VALUES (?,?,?)''', (1, proto, handle))
            self.db.commit()

        def get_proto(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT serializedUserInfo FROM profile WHERE id = 1''')
            ret = cursor.fetchone()
            if ret is None:
                return None
            return ret[0]

        def set_temp_handle(self, handle):
            cursor = self.db.cursor()
            if self.get_proto() is None:
                cursor.execute('''INSERT OR REPLACE INTO profile(id, tempHandle)
                          VALUES (?,?)''', (1, handle))
            else:
                cursor.execute('''UPDATE profile SET tempHandle=? WHERE id=?;''', (handle, 1))
            self.db.commit()

        def get_temp_handle(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT tempHandle FROM profile WHERE id = 1''')
            ret = cursor.fetchone()
            if ret is None:
                return ""
            else:
                return ret[0]

    class ListingsStore(object):
        """
        Stores a serialized `Listings` protobuf object. It contains metadata for all the
        contracts hosted by this store. We will send this in response to a GET_LISTING
        query. This should be updated each time a new contract is created.
        """

        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def add_listing(self, proto):
            """
            Will also update an existing listing if the contract hash is the same.
            """
            cursor = self.db.cursor()
            l = Listings()
            ser = self.get_proto()
            if ser is not None:
                l.ParseFromString(ser)
                for listing in l.listing:
                    if listing.contract_hash == proto.contract_hash:
                        l.listing.remove(listing)
            l.listing.extend([proto])
            cursor.execute('''INSERT OR REPLACE INTO listings(id, serializedListings)
                          VALUES (?,?)''', (1, l.SerializeToString()))
            self.db.commit()

        def delete_listing(self, hash_value):
            cursor = self.db.cursor()
            ser = self.get_proto()
            if ser is None:
                return
            l = Listings()
            l.ParseFromString(ser)
            for listing in l.listing:
                if listing.contract_hash == hash_value:
                    l.listing.remove(listing)
            cursor.execute('''INSERT OR REPLACE INTO listings(id, serializedListings)
                          VALUES (?,?)''', (1, l.SerializeToString()))
            self.db.commit()

        def delete_all_listings(self):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM listings''')
            self.db.commit()

        def get_proto(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT serializedListings FROM listings WHERE id = 1''')
            ret = cursor.fetchone()
            if ret is None:
                return None
            return ret[0]

    class KeyStore(object):
        """
        Stores the keys for this node.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def set_key(self, key_type, privkey, pubkey):
            cursor = self.db.cursor()
            cursor.execute('''INSERT OR REPLACE INTO keys(type, privkey, pubkey)
                          VALUES (?,?,?)''', (key_type, privkey, pubkey))
            self.db.commit()

        def get_key(self, key_type):
            cursor = self.db.cursor()
            cursor.execute('''SELECT privkey, pubkey FROM keys WHERE type=?''', (key_type,))
            ret = cursor.fetchone()
            if not ret:
                return None
            else:
                return ret

        def delete_all_keys(self):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM keys''')
            self.db.commit()

    class FollowData(object):
        """
        A class for saving and retrieving follower and following data
        for this node.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def follow(self, proto):
            cursor = self.db.cursor()
            f = Following()
            ser = self.get_following()
            if ser is not None:
                f.ParseFromString(ser)
                for user in f.users:
                    if user.guid == proto.guid:
                        f.users.remove(user)
            f.users.extend([proto])
            cursor.execute('''INSERT OR REPLACE INTO following(id, serializedFollowing) VALUES (?,?)''',
                           (1, f.SerializeToString()))
            self.db.commit()

        def unfollow(self, guid):
            cursor = self.db.cursor()
            f = Following()
            ser = self.get_following()
            if ser is not None:
                f.ParseFromString(ser)
                for user in f.users:
                    if user.guid == guid:
                        f.users.remove(user)
            cursor.execute('''INSERT OR REPLACE INTO following(id, serializedFollowing) VALUES (?,?)''',
                           (1, f.SerializeToString()))
            self.db.commit()

        def get_following(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT serializedFollowing FROM following WHERE id=1''')
            ret = cursor.fetchall()
            if not ret:
                return None
            else:
                return ret[0][0]

        def is_following(self, guid):
            f = Following()
            ser = self.get_following()
            if ser is not None:
                f.ParseFromString(ser)
                for user in f.users:
                    if user.guid == guid:
                        return True
            return False

        def set_follower(self, proto):
            cursor = self.db.cursor()
            f = Followers()
            ser = self.get_followers()
            if ser is not None:
                f.ParseFromString(ser)
                for follower in f.followers:
                    if follower.guid == proto.guid:
                        f.followers.remove(follower)
            f.followers.extend([proto])
            cursor.execute('''INSERT OR REPLACE INTO followers(id, serializedFollowers) VALUES (?,?)''',
                           (1, f.SerializeToString()))
            self.db.commit()

        def delete_follower(self, guid):
            cursor = self.db.cursor()
            f = Followers()
            ser = self.get_followers()
            if ser is not None:
                f.ParseFromString(ser)
                for follower in f.followers:
                    if follower.guid == guid:
                        f.followers.remove(follower)
            cursor.execute('''INSERT OR REPLACE INTO followers(id, serializedFollowers) VALUES (?,?)''',
                           (1, f.SerializeToString()))
            self.db.commit()

        def get_followers(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT serializedFollowers FROM followers WHERE id=1''')
            proto = cursor.fetchone()
            if not proto:
                return None
            else:
                return proto[0]

    class MessageStore(object):
        """
        Stores all of the chat messages for this node and allows retrieval of
        messages and conversations as well as marking as read.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def save_message(self, guid, handle, signed_pubkey, encryption_pubkey, subject,
                         message_type, message, timestamp, avatar_hash, signature, is_outgoing):
            """
            Store message in database.
            """
            outgoing = 1 if is_outgoing else 0
            msgID = digest(message + str(timestamp)).encode("hex")
            cursor = self.db.cursor()
            cursor.execute('''INSERT INTO messages(msgID, guid, handle, signedPubkey, encryptionPubkey, subject,
    messageType, message, timestamp, avatarHash, signature, outgoing, read) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (msgID, guid, handle, signed_pubkey, encryption_pubkey, subject, message_type,
                            message, timestamp, avatar_hash, signature, outgoing, 0))
            self.db.commit()

        def get_messages(self, guid, message_type):
            """
            Return all messages matching guid and message_type.
            """
            cursor = self.db.cursor()
            cursor.execute('''SELECT guid, handle, signedPubkey, encryptionPubkey, subject, messageType, message,
    timestamp, avatarHash, signature, outgoing, read FROM messages WHERE guid=? AND messageType=?''',
                           (guid, message_type))
            return cursor.fetchall()

        def get_dispute_messages(self, order_id):
            """
            Return all messages matching guid and message_type.
            """
            cursor = self.db.cursor()
            cursor.execute('''SELECT guid, handle, signedPubkey, encryptionPubkey, subject, messageType, message,
    timestamp, avatarHash, signature, outgoing, read FROM messages WHERE subject=? AND messageType=?''',
                           (order_id, "DISPUTE"))
            return cursor.fetchall()

        def get_conversations(self):
            """
            Get all 'conversations' composed of messages of type 'CHAT'.

            Returns:
              Array of dictionaries, one element for each guid. Dictionaries
              include last message only."""
            cursor = self.db.cursor()
            cursor.execute('''SELECT DISTINCT guid FROM messages''',)
            guids = cursor.fetchall()
            ret = []
            unread = self.get_unread()
            for g in guids:
                cursor.execute('''SELECT avatarHash, message, max(timestamp), encryptionPubkey FROM messages
WHERE guid=? and messageType=?''', (g[0], "CHAT"))
                val = cursor.fetchone()
                if val[0] is not None:
                    ret.append({"guid": g[0],
                                "avatar_hash": val[0].encode("hex"),
                                "last_message": val[1],
                                "timestamp": val[2],
                                "encryption_key": val[3].encode("hex"),
                                "unread": 0 if g[0] not in unread else unread[g[0]]})
            return ret

        def get_unread(self):
            """
            Get Counter of guids which have unread, incoming messages.
            """
            cursor = self.db.cursor()
            cursor.execute('''SELECT guid FROM messages WHERE read=0 and outgoing=0''',)
            ret = []
            guids = cursor.fetchall()
            for g in guids:
                ret.append(g[0])
            return Counter(ret)

        def mark_as_read(self, guid):
            """
            Mark all messages for guid as read.
            """
            cursor = self.db.cursor()
            cursor.execute('''UPDATE messages SET read=? WHERE guid=?;''', (1, guid))
            self.db.commit()

        def delete_message(self, guid):
            """
            Delete all messages of type 'CHAT' for guid.
            """
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM messages WHERE guid=? AND messageType="CHAT"''', (guid, ))
            self.db.commit()

    class NotificationStore(object):
        """
        All notifications are stored here.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def save_notification(self, notif_id, guid, handle, notif_type, order_id, title, timestamp, image_hash):
            cursor = self.db.cursor()
            cursor.execute('''INSERT INTO notifications(id, guid, handle, type, orderId, title, timestamp,
imageHash, read) VALUES (?,?,?,?,?,?,?,?,?)''', (notif_id, guid, handle, notif_type, order_id, title, timestamp,
                                                 image_hash, 0))
            self.db.commit()

        def get_notifications(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id, guid, handle, type, orderId, title, timestamp,
imageHash, read FROM notifications''')
            return cursor.fetchall()

        def mark_as_read(self, notif_id):
            cursor = self.db.cursor()
            cursor.execute('''UPDATE notifications SET read=? WHERE id=?;''', (1, notif_id))
            self.db.commit()

        def delete_notification(self, notif_id):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM notifications WHERE id=?''', (notif_id,))
            self.db.commit()

    class BroadcastStore(object):
        """
        Stores broadcast messages that our node receives.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def save_broadcast(self, broadcast_id, guid, handle, message, timestamp, avatar_hash):
            cursor = self.db.cursor()
            cursor.execute('''INSERT INTO broadcasts(id, guid, handle, message, timestamp, avatarHash)
    VALUES (?,?,?,?,?,?)''', (broadcast_id, guid, handle, message, timestamp, avatar_hash))
            self.db.commit()

        def get_broadcasts(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id, guid, handle, message, timestamp, avatarHash FROM broadcasts''')
            return cursor.fetchall()

        def delete_broadcast(self, broadcast_id):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM broadcasts WHERE id=?''', (broadcast_id,))
            self.db.commit()

    class VendorStore(object):
        """
        Stores a list of vendors this node has heard about. Useful for
        filling out data in the homepage.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def save_vendor(self, guid, serialized_node):
            cursor = self.db.cursor()
            try:
                cursor.execute('''INSERT OR REPLACE INTO vendors(guid, serializedNode)
    VALUES (?,?)''', (guid, serialized_node))
            except Exception as e:
                print e.message
            self.db.commit()

        def get_vendors(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT serializedNode FROM vendors''')
            ret = cursor.fetchall()
            nodes = []
            for n in ret:
                try:
                    proto = objects.Node()
                    proto.ParseFromString(n[0])
                    node = Node(proto.guid,
                                proto.nodeAddress.ip,
                                proto.nodeAddress.port,
                                proto.signedPublicKey,
                                None if not proto.HasField("relayAddress") else
                                (proto.relayAddress.ip, proto.relayAddress.port),
                                proto.natType,
                                proto.vendor)
                    nodes.append(node)
                except Exception, e:
                    print e.message
            return nodes

        def delete_vendor(self, guid):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM vendors WHERE guid=?''', (guid,))
            self.db.commit()

    class ModeratorStore(object):
        """
        Stores a list of known moderators. A moderator must be saved here
        for it to be used in a new listing.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def save_moderator(self, guid, signed_pubkey, encryption_key, encription_sig,
                           bitcoin_key, bicoin_sig, name, avatar_hash, fee, handle="", short_desc=""):
            cursor = self.db.cursor()
            try:
                cursor.execute('''INSERT OR REPLACE INTO moderators(guid, signedPubkey, encryptionKey,
    encryptionSignature, bitcoinKey, bitcoinSignature, handle, name, description, avatar, fee)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (guid, signed_pubkey, encryption_key, encription_sig, bitcoin_key,
                                        bicoin_sig, handle, name, short_desc, avatar_hash, fee))
            except Exception as e:
                print e.message
            self.db.commit()

        def get_moderator(self, guid):
            cursor = self.db.cursor()
            cursor.execute('''SELECT guid, signedPubkey, encryptionKey, encryptionSignature, bitcoinKey,
     bitcoinSignature, handle, name, description, avatar, fee FROM moderators WHERE guid=?''', (guid,))
            return cursor.fetchone()

        def delete_moderator(self, guid):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM moderators WHERE guid=?''', (guid,))
            self.db.commit()

        def clear_all(self):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM moderators''')
            self.db.commit()

    class Purchases(object):
        """
        Stores a list of this node's purchases.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def new_purchase(self, order_id, title, description, timestamp, btc,
                         address, status, thumbnail, vendor, proofSig, contract_type):
            cursor = self.db.cursor()
            try:
                cursor.execute('''INSERT OR REPLACE INTO purchases(id, title, description, timestamp, btc,
address, status, thumbnail, vendor, proofSig, contractType) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                               (order_id, title, description, timestamp, btc, address,
                                status, thumbnail, vendor, proofSig, contract_type))
            except Exception as e:
                print e.message
            self.db.commit()

        def get_purchase(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id, title, description, timestamp, btc, address, status,
     thumbnail, vendor, contractType, proofSig FROM purchases WHERE id=?''', (order_id,))
            ret = cursor.fetchall()
            if not ret:
                return None
            else:
                return ret[0]

        def delete_purchase(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM purchases WHERE id=?''', (order_id,))
            self.db.commit()

        def get_all(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id, title, description, timestamp, btc, status,
     thumbnail, vendor, contractType FROM purchases ''')
            return cursor.fetchall()

        def get_unfunded(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id FROM purchases WHERE status=0''')
            return cursor.fetchall()

        def update_status(self, order_id, status):
            cursor = self.db.cursor()
            cursor.execute('''UPDATE purchases SET status=? WHERE id=?;''', (status, order_id))
            self.db.commit()

        def get_status(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT status FROM purchases WHERE id=?''', (order_id,))
            ret = cursor.fetchone()
            if not ret:
                return None
            else:
                return ret[0]

        def update_outpoint(self, order_id, outpoint):
            cursor = self.db.cursor()
            cursor.execute('''UPDATE purchases SET outpoint=? WHERE id=?;''', (outpoint, order_id))
            self.db.commit()

        def get_outpoint(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT outpoint FROM purchases WHERE id=?''', (order_id,))
            ret = cursor.fetchone()
            if not ret:
                return None
            else:
                return ret[0]

        def get_proof_sig(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT proofSig FROM purchases WHERE id=?''', (order_id,))
            ret = cursor.fetchone()
            if not ret:
                return None
            else:
                return ret[0]

    class Sales(object):
        """
        Stores a list of this node's sales.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def new_sale(self, order_id, title, description, timestamp, btc,
                     address, status, thumbnail, buyer, contract_type):
            cursor = self.db.cursor()
            try:
                cursor.execute('''INSERT OR REPLACE INTO sales(id, title, description, timestamp, btc, address,
status, thumbnail, buyer, contractType) VALUES (?,?,?,?,?,?,?,?,?,?)''',
                               (order_id, title, description, timestamp, btc, address, status,
                                thumbnail, buyer, contract_type))
            except Exception as e:
                print e.message
            self.db.commit()

        def get_sale(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id, title, description, timestamp, btc, address, status,
    thumbnail, buyer, contractType FROM sales WHERE id=?''', (order_id,))
            ret = cursor.fetchall()
            if not ret:
                return None
            else:
                return ret[0]

        def delete_sale(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM sales WHERE id=?''', (order_id,))
            self.db.commit()

        def get_all(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id, title, description, timestamp, btc, status,
    thumbnail, buyer, contractType FROM sales ''')
            return cursor.fetchall()

        def get_unfunded(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id FROM sales WHERE status=0''')
            return cursor.fetchall()

        def update_status(self, order_id, status):
            cursor = self.db.cursor()
            cursor.execute('''UPDATE sales SET status=? WHERE id=?;''', (status, order_id))
            self.db.commit()

        def get_status(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT status FROM sales WHERE id=?''', (order_id,))
            ret = cursor.fetchone()
            if not ret:
                return None
            else:
                return ret[0]

        def update_outpoint(self, order_id, outpoint):
            cursor = self.db.cursor()
            cursor.execute('''UPDATE sales SET outpoint=? WHERE id=?;''', (outpoint, order_id))
            self.db.commit()

        def update_payment_tx(self, order_id, txid):
            cursor = self.db.cursor()
            cursor.execute('''UPDATE sales SET paymentTX=? WHERE id=?;''', (txid, order_id))
            self.db.commit()

        def get_outpoint(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT outpoint FROM sales WHERE id=?''', (order_id,))
            ret = cursor.fetchone()
            if not ret:
                return None
            else:
                return ret[0]

    class Cases(object):
        """
        Stores a list of this node's moderation cases.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def new_case(self, order_id, title, timestamp, order_date, btc,
                     thumbnail, buyer, vendor, validation, claim):
            cursor = self.db.cursor()
            try:
                cursor.execute('''INSERT OR REPLACE INTO cases(id, title, timestamp, orderDate, btc, thumbnail,
buyer, vendor, validation, claim, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                               (order_id, title, timestamp, order_date, btc,
                                thumbnail, buyer, vendor, validation, claim, 0))
            except Exception as e:
                print e.message
            self.db.commit()

        def delete_case(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''DELETE FROM cases WHERE id=?''', (order_id,))
            self.db.commit()

        def get_all(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT id, title, timestamp, orderDate, btc, thumbnail,
buyer, vendor, validation, claim, status FROM cases ''')
            return cursor.fetchall()

        def get_claim(self, order_id):
            cursor = self.db.cursor()
            cursor.execute('''SELECT claim FROM cases WHERE id=?''', (order_id,))
            ret = cursor.fetchone()
            if not ret:
                return None
            else:
                return ret[0]

        def update_status(self, order_id, status):
            cursor = self.db.cursor()
            cursor.execute('''UPDATE cases SET status=? WHERE id=?;''', (status, order_id))
            self.db.commit()

    class Settings(object):
        """
        Stores the UI settings.
        """
        def __init__(self):
            self.db = lite.connect(DATABASE)
            self.db.text_factory = str

        def update(self, refundAddress, currencyCode, country, language, timeZone, notifications,
                   shipping_addresses, blocked, libbitcoinServer, ssl, seed, terms_conditions,
                   refund_policy, resolver, moderator_list):
            cursor = self.db.cursor()
            cursor.execute('''INSERT OR REPLACE INTO settings(id, refundAddress, currencyCode, country,
language, timeZone, notifications, shippingAddresses, blocked, libbitcoinServer, ssl, seed,
termsConditions, refundPolicy, resolver, moderatorList) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                           (1, refundAddress, currencyCode, country, language, timeZone,
                            notifications, shipping_addresses, blocked,
                            libbitcoinServer, ssl, seed, terms_conditions,
                            refund_policy, resolver, moderator_list))
            self.db.commit()

        def get(self):
            cursor = self.db.cursor()
            cursor.execute('''SELECT * FROM settings WHERE id=1''')
            return cursor.fetchone()


def _database_path(testnet, filepath):
    '''
    Get database pathname.

    Args:
      testnet: Boolean
      filename: If provided, overrides testnet
    '''
    path = ''

    if filepath:
        path = filepath
    elif testnet:
        path = join(DATA_FOLDER, "OB-Testnet.db")
    else:
        path = join(DATA_FOLDER, "OB-Mainnet.db")

    return path


def _initialize_database(database):
    '''
    Create database, if not present, and clear cache.
    '''
    if not database:
        raise RuntimeError('attempted to initialize empty path')

    if not os.path.isfile(database):
        _create_database(database)
        cache = join(DATA_FOLDER, "cache.pickle")
        if os.path.exists(cache):
            os.remove(cache)


def _initialize_datafolder_tree():
    '''
    Creates, if not present, directory tree in DATA_FOLDER.
    '''
    tree = [
        ['cache'],
        ['store', 'contracts', 'listings'],
        ['store', 'contracts', 'in progress'],
        ['store', 'contracts', 'unfunded'],
        ['store', 'contracts', 'trade receipts'],
        ['store', 'media'],
        ['purchases', 'in progress'],
        ['purchases', 'unfunded'],
        ['purchases', 'trade receipts'],
        ['cases']
    ]

    path = ''
    for sub_tree in tree:
        path = DATA_FOLDER
        for directory in sub_tree:
            path = join(path, directory)
        if not os.path.exists(path):
            os.makedirs(path)


def _create_database(database):
    db = lite.connect(database)
    cursor = db.cursor()

    cursor.execute('''PRAGMA user_version = 0''')
    cursor.execute('''CREATE TABLE hashmap(hash TEXT PRIMARY KEY, filepath TEXT)''')

    cursor.execute('''CREATE TABLE profile(id INTEGER PRIMARY KEY, serializedUserInfo BLOB, tempHandle TEXT)''')

    cursor.execute('''CREATE TABLE listings(id INTEGER PRIMARY KEY, serializedListings BLOB)''')

    cursor.execute('''CREATE TABLE keys(type TEXT PRIMARY KEY, privkey BLOB, pubkey BLOB)''')

    cursor.execute('''CREATE TABLE followers(id INTEGER PRIMARY KEY, serializedFollowers BLOB)''')

    cursor.execute('''CREATE TABLE following(id INTEGER PRIMARY KEY, serializedFollowing BLOB)''')

    cursor.execute('''CREATE TABLE messages(msgID TEXT PRIMARY KEY, guid TEXT, handle TEXT, signedPubkey BLOB,
encryptionPubkey BLOB, subject TEXT, messageType TEXT, message TEXT, timestamp INTEGER,
avatarHash BLOB, signature BLOB, outgoing INTEGER, read INTEGER)''')
    cursor.execute('''CREATE INDEX index_guid ON messages(guid);''')
    cursor.execute('''CREATE INDEX index_subject ON messages(subject);''')
    cursor.execute('''CREATE INDEX index_messages_read ON messages(read);''')

    cursor.execute('''CREATE TABLE notifications(id TEXT PRIMARY KEY, guid BLOB, handle TEXT, type TEXT,
orderId TEXT, title TEXT, timestamp INTEGER, imageHash BLOB, read INTEGER)''')

    cursor.execute('''CREATE TABLE broadcasts(id TEXT PRIMARY KEY, guid BLOB, handle TEXT, message TEXT,
timestamp INTEGER, avatarHash BLOB)''')

    cursor.execute('''CREATE TABLE vendors(guid TEXT PRIMARY KEY, serializedNode BLOB)''')

    cursor.execute('''CREATE TABLE moderators(guid TEXT PRIMARY KEY, signedPubkey BLOB, encryptionKey BLOB,
encryptionSignature BLOB, bitcoinKey BLOB, bitcoinSignature BLOB, handle TEXT, name TEXT, description TEXT,
avatar BLOB, fee FLOAT)''')

    cursor.execute('''CREATE TABLE purchases(id TEXT PRIMARY KEY, title TEXT, description TEXT,
timestamp INTEGER, btc FLOAT, address TEXT, status INTEGER, outpoint BLOB, thumbnail BLOB, vendor TEXT,
proofSig BLOB, contractType TEXT)''')

    cursor.execute('''CREATE TABLE sales(id TEXT PRIMARY KEY, title TEXT, description TEXT,
timestamp INTEGER, btc REAL, address TEXT, status INTEGER, thumbnail BLOB, outpoint BLOB, buyer TEXT,
paymentTX TEXT, contractType TEXT)''')

    cursor.execute('''CREATE TABLE cases(id TEXT PRIMARY KEY, title TEXT, timestamp INTEGER, orderDate TEXT,
btc REAL, thumbnail BLOB, buyer TEXT, vendor TEXT, validation TEXT, claim TEXT, status INTEGER)''')

    cursor.execute('''CREATE TABLE settings(id INTEGER PRIMARY KEY, refundAddress TEXT, currencyCode TEXT,
country TEXT, language TEXT, timeZone TEXT, notifications INTEGER, shippingAddresses BLOB, blocked BLOB,
libbitcoinServer TEXT, SSL INTEGER, seed TEXT, termsConditions TEXT, refundPolicy TEXT, moderatorList BLOB,
resolver TEXT)''')

    db.commit()
